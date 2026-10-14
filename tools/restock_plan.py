"""Build the encrypted Restock Planner report (owner view + supplier mirror) for the Indifeels dashboard.

Same logic as the Power BI restock model:
  * Published date = custom.published_date_old for products migrated from WooCommerce (created before
    18 Apr 2026 11pm UTC); otherwise the Shopify created date (Melbourne).
  * Sales = lifetime units. Variant sales by variant id, product sales by product id (so migrated orders that
    lost their variant still count at product level). Cancelled orders are not counted.
  * Variants with the same title inside a product are merged (stock and sales summed).
The page does the maths (days to sell, required stock x leniency, days to stockout), so the leniency slider is live.

Needs the read_all_orders scope on SHOPIFY_TOKEN: without it Shopify silently returns only ~60 days of orders and
every number would be wrong, so the build FAILS (and the last good report stays published).

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY
Writes: r/restock-plan.bin, r/restock-plan.meta.bin, r/status.json
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv  # reuse gql, write_encrypted, set_status

RID = "restock-plan"
MEL = ZoneInfo("Australia/Melbourne")
SYD = ZoneInfo("Australia/Sydney")
MIGRATION_CUTOFF = dt.datetime(2026, 4, 18, 23, 0, tzinfo=dt.timezone.utc)

PRODUCTS = """{ products(query:"status:active"){ edges{ node{
  id title createdAt featuredImage{ url }
  metafield(namespace:"custom", key:"published_date_old"){ value }
  supplier: metafield(namespace:"custom", key:"supplier_name"){ value }
  variants{ edges{ node{ id title inventoryQuantity } } } } } } }"""
ORDERS = """{ orders{ edges{ node{ id cancelledAt lineItems{ edges{ node{ id quantity variant{ id } product{ id } } } } } } } }"""
SCOPES = "query { currentAppInstallation { accessScopes { handle } } }"
START = "mutation($q:String!){ bulkOperationRunQuery(query:$q){ bulkOperation{ id status } userErrors{ field message } } }"
POLL = "query($id:ID!){ node(id:$id){ ... on BulkOperation { status errorCode objectCount url } } }"
CURRENT = "query { currentBulkOperation(type: QUERY) { id status } }"


def num(gid):
    return gid.rsplit("/", 1)[-1] if gid else None


def bulk(inner, label, max_wait=1500):
    # one bulk query at a time per shop: wait for any running one (e.g. another report) to finish first
    waited = 0
    while waited < 600:
        cur = (pv.gql(CURRENT, {})["data"].get("currentBulkOperation") or {})
        if cur.get("status") not in ("CREATED", "RUNNING"):
            break
        time.sleep(10)
        waited += 10
    d = pv.gql(START, {"q": inner})["data"]["bulkOperationRunQuery"]
    if d["userErrors"]:
        raise RuntimeError(f"{label} bulk query refused: {json.dumps(d['userErrors'])[:200]}")
    op_id = d["bulkOperation"]["id"]
    t0 = time.time()
    while True:
        time.sleep(5)
        op = pv.gql(POLL, {"id": op_id})["data"]["node"]
        if op["status"] == "COMPLETED":
            if not op.get("url"):
                return []
            with urllib.request.urlopen(op["url"], timeout=300) as r:
                return [json.loads(line) for line in r.read().decode("utf-8").splitlines() if line.strip()]
        if op["status"] in ("FAILED", "CANCELED", "EXPIRED"):
            raise RuntimeError(f"{label} bulk operation {op['status']} {op.get('errorCode') or ''}".strip())
        if time.time() - t0 > max_wait:
            raise RuntimeError(f"{label} bulk operation timed out")


def require_scopes():
    scopes = {x["handle"] for x in pv.gql(SCOPES, {})["data"]["currentAppInstallation"]["accessScopes"]}
    missing = {"read_products", "read_orders", "read_all_orders"} - scopes
    if missing:
        raise RuntimeError("Shopify token is missing scope(s): " + ", ".join(sorted(missing)) +
                           ". Add them to the custom app, then re-run. Sales history would be incomplete otherwise")


def melbourne_day(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(MEL).strftime("%Y-%m-%d")


def build():
    require_scopes()
    prod_lines = bulk(PRODUCTS, "products")
    order_lines = bulk(ORDERS, "orders")

    # orders: bulk output is one JSON object per line; line items point at their order by __parentId
    cancelled = {l["id"] for l in order_lines if "/Order/" in l.get("id", "") and l.get("cancelledAt")}
    variant_sold, product_sold, lines = {}, {}, 0
    for l in order_lines:
        if "/LineItem/" not in l.get("id", "") or l.get("__parentId") in cancelled:
            continue
        lines += 1
        q = int(l.get("quantity") or 0)
        vid, pid = num((l.get("variant") or {}).get("id")), num((l.get("product") or {}).get("id"))
        if vid:
            variant_sold[vid] = variant_sold.get(vid, 0) + q
        if pid:
            product_sold[pid] = product_sold.get(pid, 0) + q
    if lines < 50:
        raise RuntimeError(f"Only {lines} order lines came back: refusing to publish incomplete sales history")

    products, order = {}, []
    for l in prod_lines:
        if "/Product/" in l.get("id", "") and "__parentId" not in l:
            created = dt.datetime.fromisoformat(l["createdAt"].replace("Z", "+00:00"))
            meta = ((l.get("metafield") or {}).get("value") or "")
            migrated = created < MIGRATION_CUTOFF
            from_meta = bool(migrated and re.match(r"^\d{4}-\d{2}-\d{2}", meta))
            products[l["id"]] = {
                "id": num(l["id"]), "title": l["title"],
                "image": ((l.get("featuredImage") or {}).get("url")) or "",
                "published": meta[:10] if from_meta else melbourne_day(l["createdAt"]),
                "supplier": re.sub(r"^\s*\d+\s*:\s*", "", ((l.get("supplier") or {}).get("value") or "")).strip(),  # "52908 : Pankaj" -> "Pankaj"
                "fromMeta": from_meta, "migrated": migrated, "variants": {},
            }
            order.append(l["id"])
    for l in prod_lines:
        if "/ProductVariant/" in l.get("id", "") and l.get("__parentId") in products:
            p = products[l["__parentId"]]
            key = l["title"].strip().lower()
            cur = p["variants"].setdefault(key, [l["title"], 0, 0])
            cur[1] += int(l.get("inventoryQuantity") or 0)
            cur[2] += variant_sold.get(num(l["id"]), 0)

    out = []
    for gid in order:
        p = products[gid]
        sales = product_sold.get(p["id"], 0)
        if sales <= 0:
            continue      # nothing ever sold: no days-to-sell, nothing to restock
        out.append({"id": p["id"], "title": p["title"], "image": p["image"], "published": p["published"],
                    "supplier": p["supplier"], "sales": sales, "variants": list(p["variants"].values())})
    no_meta = sum(1 for p in products.values() if p["migrated"] and not p["fromMeta"])

    now = dt.datetime.now(SYD)
    updated = now.strftime("%d %b %Y, %H:%M")
    data = {"generatedAt": now.isoformat(),
            "source": f"Shopify · {len(products)} active products ({len(out)} with sales) · {lines:,} order lines, full history",
            "products": out}
    page = open(os.path.join(pv.ROOT, "tools", "restock_plan_template.html"), encoding="utf-8").read()
    assert page.count("__DATA__") == 1
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))

    oos = sum(1 for p in out for v in p["variants"] if v[1] <= 0 and v[2] > 0)
    meta = {"updated": updated, "stats": [[str(len(out)), "products selling"], [str(oos), "sold-out variants"]],
            "warn": f"{no_meta} migrated products have no published_date_old" if no_meta > 25 else ""}
    key = os.environ["STOCK_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"products": len(products), "with_sales": len(out), "order_lines": lines, "sold_out_variants": oos,
                      "migrated_without_metafield": no_meta, "page_kb": round(len(page) / 1024)}))


if __name__ == "__main__":
    pv.RID = RID
    try:
        build()
    except Exception as exc:
        pv.RID = RID
        try:
            pv.set_status(False, f"Restock Planner build failed: {str(exc)[:160]}")
        except Exception:
            pass
        raise
