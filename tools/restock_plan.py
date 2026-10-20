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

Also: variant/product last-sold day + units sold in the last 30 days (for the "by date" sort and the spike damping),
variant barcodes (scan box), collections (collection filter), custom.discountinued (yes/no), and the discontinued sync: changes made in the planner
(Supabase restock_discontinued) are pushed to the Shopify metafield here, then marked done. A sync failure never fails the
build (needs write_products on the token; the planner still honours the choice meanwhile).

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY, SYNC_READ_TOKEN (optional: without it the discontinued sync is skipped)
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
  id title createdAt onlineStoreUrl featuredImage{ url }
  metafield(namespace:"custom", key:"published_date_old"){ value }
  supplier: metafield(namespace:"custom", key:"supplier_name"){ value }
  disc: metafield(namespace:"custom", key:"discountinued"){ value }
  collections{ edges{ node{ id title } } }
  variants{ edges{ node{ id title inventoryQuantity barcode } } } } } } }"""
ORDERS = """{ orders{ edges{ node{ id cancelledAt processedAt lineItems{ edges{ node{ id quantity variant{ id } product{ id } } } } } } } }"""
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


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://yrigvovwyfpaybibfjva.supabase.co")
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_8xv46B6mvnAN2McGDc4VEg_pNF0qHvD")  # public publishable key, same as the other builders
SET_META = """mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ metafields{ id } userErrors{ field message code } } }"""
DEL_META = """mutation($m:[MetafieldIdentifierInput!]!){ metafieldsDelete(metafields:$m){ deletedMetafields{ key } userErrors{ field message } } }"""


def sb_rpc(name, body):
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/rpc/{name}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "apikey": SUPABASE_ANON}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=60))


def sync_product_cols(products):
    """Tell Supabase which collections each product is in (supplier logins linked to a collection only see those). Never raises."""
    token = os.environ.get("SYNC_READ_TOKEN")
    if not token:
        return
    rows = [{"product_id": str(p["id"]), "cols": p["cols"]} for p in products.values() if p.get("id")]
    try:
        for i in range(0, len(rows), 400):
            sb_rpc("sync_set_restock_product_cols", {"p_token": token, "p_rows": rows[i:i + 400]})
        print("product collections synced:", len(rows))
    except Exception as exc:
        print("product collection sync skipped:", str(exc)[:120])


def sync_discontinued():
    """Push 'discontinued' choices made in the planner to Shopify (custom.discountinued yes/no + date). Never raises."""
    token = os.environ.get("SYNC_READ_TOKEN")
    if not token:
        print("discontinued sync skipped: SYNC_READ_TOKEN not set")
        return 0
    try:
        pending = sb_rpc("sync_get_restock_discontinued", {"p_token": token})
    except Exception as exc:  # the migration may not be applied yet
        print("discontinued sync skipped:", str(exc)[:120])
        return 0
    done = []
    today = dt.datetime.now(MEL).strftime("%Y-%m-%d")
    for r in pending:
        pid = str(r["product_id"])
        if not pid.isdigit():
            continue
        gid = f"gid://shopify/Product/{pid}"
        try:
            yes = bool(r["discontinued"])
            m = [{"ownerId": gid, "namespace": "custom", "key": "discountinued", "type": "single_line_text_field", "value": "yes" if yes else "no"}]
            if yes:
                m.append({"ownerId": gid, "namespace": "custom", "key": "discountinued_date", "type": "date", "value": today})
            res = pv.gql(SET_META, {"m": m})["data"]["metafieldsSet"]
            if res["userErrors"]:
                print("discontinued sync: Shopify refused", pid, json.dumps(res["userErrors"])[:160])
                continue
            if not yes:
                try:
                    pv.gql(DEL_META, {"m": [{"ownerId": gid, "namespace": "custom", "key": "discountinued_date"}]})
                except Exception:
                    pass
            done.append(pid)
        except Exception as exc:
            print("discontinued sync: failed for", pid, str(exc)[:120])
    if done:
        try:
            sb_rpc("sync_mark_restock_discontinued", {"p_token": token, "p_ids": done})
        except Exception as exc:
            print("discontinued sync: could not mark done:", str(exc)[:120])
    print(f"discontinued sync: {len(done)} of {len(pending)} pushed to Shopify")
    return len(done)


DEL_VARIANT = """mutation($p:ID!,$v:[ID!]!){ productVariantsBulkDelete(productId:$p, variantsIds:$v){ userErrors{ field message } } }"""


def sync_size_deletes(prod_lines):
    """Sizes removed with "Remove from dashboard and Shopify": delete the variant in Shopify. Safety rails: only when its stock is 0,
    never the last variant of a product. Anything refused stays hidden in the app only and the reason is stored. Never raises."""
    token = os.environ.get("SYNC_READ_TOKEN")
    if not token:
        return
    try:
        pending = sb_rpc("sync_get_restock_size_deletes", {"p_token": token})
    except Exception as exc:  # the migration may not be applied yet
        print("size delete sync skipped:", str(exc)[:120])
        return
    results, gone = [], set()
    for r in pending:
        pid, title = str(r["product_id"]), (r["variant_title"] or "").strip().lower()
        mine = [l for l in prod_lines if "/ProductVariant/" in l.get("id", "") and num(l.get("__parentId", "")) == pid]
        hit = [l for l in mine if (l.get("title") or "").strip().lower() == title]
        err = None
        if not hit:
            pass                                    # already gone from Shopify: nothing to delete
        elif len(mine) < 2:
            err = "last size of the product: can't be deleted"
        elif int(hit[0].get("inventoryQuantity") or 0) > 0:
            err = f"still has {int(hit[0].get('inventoryQuantity') or 0)} in stock: set it to 0 first"
        else:
            try:
                res = pv.gql(DEL_VARIANT, {"p": f"gid://shopify/Product/{pid}", "v": [hit[0]["id"]]})["data"]["productVariantsBulkDelete"]
                if res["userErrors"]:
                    err = json.dumps(res["userErrors"])[:200]
                else:
                    gone.add(hit[0]["id"])
            except Exception as exc:
                err = str(exc)[:200]
        if err:
            print("size delete sync: not deleted", r["vkey"], err)
        results.append({"vkey": r["vkey"], "ok": err is None, "error": err})
    if gone:
        prod_lines[:] = [l for l in prod_lines if l.get("id") not in gone]     # this build already reflects it
    if results:
        try:
            sb_rpc("sync_mark_restock_size_deletes", {"p_token": token, "p_rows": results})
        except Exception as exc:
            print("size delete sync: could not mark done:", str(exc)[:120])
    print(f"size delete sync: {len(gone)} of {len(pending)} deleted in Shopify")


SUP_DEF = """{ metafieldDefinitions(first:1, ownerType:PRODUCT, namespace:"custom", key:"supplier_name"){ nodes{ validations{ name value } } } }"""
SUP_DEF_SET = """mutation($d:MetafieldDefinitionUpdateInput!){ metafieldDefinitionUpdate(definition:$d){ updatedDefinition{ id } userErrors{ field message } } }"""


def supplier_choices():
    """Supplier names allowed on Shopify's custom.supplier_name (its 'choices' list). Never raises."""
    try:
        for n in pv.gql(SUP_DEF, {})["data"]["metafieldDefinitions"]["nodes"][:1]:
            for v in n["validations"]:
                if v["name"] == "choices":
                    return [str(x) for x in json.loads(v["value"])]
    except Exception as exc:
        print("supplier choices unavailable:", str(exc)[:120])
    return []


def add_supplier_choice(name, choices):
    """Add a brand-new supplier name to the Shopify choices list so it can be set on products (and then shows in every dropdown)."""
    if not choices:
        print("supplier choice add skipped: could not read the current list")   # never overwrite the list blind
        return False
    if any(c.strip().lower() == name.strip().lower() for c in choices):
        return True
    try:
        res = pv.gql(SUP_DEF_SET, {"d": {"namespace": "custom", "key": "supplier_name", "ownerType": "PRODUCT",
                                          "validations": [{"name": "choices", "value": json.dumps(choices + [name], ensure_ascii=False)}]}})["data"]["metafieldDefinitionUpdate"]
        if res["userErrors"]:
            print("supplier choice add refused:", json.dumps(res["userErrors"])[:160])
            return False
        choices.append(name)
        return True
    except Exception as exc:
        print("supplier choice add failed:", str(exc)[:120])
        return False


BAD_BACKFILL_TAGS = {("9699978019173", "Pankaj"), ("9699978084709", "Vistara"), ("9699978674533", "Vistara"), ("9700037460325", "Vistara"),
                     ("9700053778789", "Vistara"), ("9700056039781", "Vistara"), ("9700056138085", "Vistara")}   # (product, name) pairs the owner never re-tagged


def sync_supplier_tags(prod_lines, choices):
    """Suppliers who picked an untagged product become its supplier. Push to Shopify custom.supplier_name
    (copying the existing "id : Name" spelling when known) and overlay on this build. Never raises."""
    token = os.environ.get("SYNC_READ_TOKEN")
    if not token:
        return
    try:
        tags = sb_rpc("sync_get_restock_product_tags", {"p_token": token})
    except Exception as exc:
        print("supplier tag sync skipped:", str(exc)[:120])
        return
    prods = {num(l["id"]): l for l in prod_lines if "/Product/" in l.get("id", "") and "__parentId" not in l}
    full = {}
    for l in prods.values():
        raw = ((l.get("supplier") or {}).get("value") or "").strip()
        if raw:
            full.setdefault(re.sub(r"^\s*\d+\s*:\s*", "", raw).strip().lower(), raw)
    done = []
    for t in tags:
        pid = str(t["product_id"])
        if (pid, t["supplier"].strip()) in BAD_BACKFILL_TAGS and not t["synced"]:
            continue                      # bulk back-fill from old order claims (wrong names, never confirmed by the owner): ignore
        l = prods.get(pid)
        if not l:
            continue
        cur = ((l.get("supplier") or {}).get("value") or "").strip()
        if not t["supplier"].strip():     # owner removed the supplier: clear it on Shopify too
            if t["synced"]:
                continue
            try:
                if cur:
                    res = pv.gql(DEL_META, {"m": [{"ownerId": l["id"], "namespace": "custom", "key": "supplier_name"}]})["data"]["metafieldsDelete"]
                    if res["userErrors"]:
                        print("supplier tag sync: Shopify refused delete", pid, json.dumps(res["userErrors"])[:160])
                        continue
                l["supplier"] = {"value": ""}
                done.append(pid)
            except Exception as exc:
                print("supplier tag sync: delete failed for", pid, str(exc)[:120])
            continue
        val = full.get(t["supplier"].strip().lower(), t["supplier"].strip())
        force = bool(t.get("override"))
        if cur and not (force and not t["synced"]):
            if not t["synced"]:
                done.append(pid)          # somebody tagged it in Shopify meanwhile: Shopify wins
            continue
        if cur and re.sub(r"^\s*\d+\s*:\s*", "", cur).strip().lower() == t["supplier"].strip().lower():
            done.append(pid)              # Shopify already has this supplier
            continue
        l["supplier"] = {"value": val}    # show it on this build either way
        if t["synced"]:
            continue
        try:
            if not re.match(r"^\s*\d+\s*:", val) and not add_supplier_choice(val, choices):
                continue
            res = pv.gql(SET_META, {"m": [{"ownerId": l["id"], "namespace": "custom", "key": "supplier_name", "type": "single_line_text_field", "value": val}]})["data"]["metafieldsSet"]
            if res["userErrors"]:
                print("supplier tag sync: Shopify refused", pid, json.dumps(res["userErrors"])[:160])
                continue
            done.append(pid)
        except Exception as exc:
            print("supplier tag sync: failed for", pid, str(exc)[:120])
    if done:
        try:
            sb_rpc("sync_mark_restock_product_tags", {"p_token": token, "p_ids": done})
        except Exception as exc:
            print("supplier tag sync: could not mark done:", str(exc)[:120])
    print(f"supplier tag sync: {len(done)} of {len(tags)} tags pushed to Shopify")


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
    sync_discontinued()          # before reading products, so this build already carries the new value
    prod_lines = bulk(PRODUCTS, "products")
    choices = supplier_choices()
    sync_supplier_tags(prod_lines, choices)
    sync_size_deletes(prod_lines)
    order_lines = bulk(ORDERS, "orders")

    # orders: bulk output is one JSON object per line; line items point at their order by __parentId
    cancelled = {l["id"] for l in order_lines if "/Order/" in l.get("id", "") and l.get("cancelledAt")}
    placed = {l["id"]: melbourne_day(l["processedAt"]) for l in order_lines if "/Order/" in l.get("id", "") and l.get("processedAt")}
    since30 = (dt.datetime.now(MEL) - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    variant_sold, product_sold, lines = {}, {}, 0
    variant_last, product_last, variant_30, product_30 = {}, {}, {}, {}
    for l in order_lines:
        if "/LineItem/" not in l.get("id", "") or l.get("__parentId") in cancelled:
            continue
        lines += 1
        q = int(l.get("quantity") or 0)
        vid, pid = num((l.get("variant") or {}).get("id")), num((l.get("product") or {}).get("id"))
        day = placed.get(l.get("__parentId"), "")
        if vid:
            variant_sold[vid] = variant_sold.get(vid, 0) + q
            if day > variant_last.get(vid, ""):
                variant_last[vid] = day
            if day >= since30:
                variant_30[vid] = variant_30.get(vid, 0) + q
        if pid:
            product_sold[pid] = product_sold.get(pid, 0) + q
            if day > product_last.get(pid, ""):
                product_last[pid] = day
            if day >= since30:
                product_30[pid] = product_30.get(pid, 0) + q
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
                "image": ((l.get("featuredImage") or {}).get("url")) or "", "url": l.get("onlineStoreUrl") or "",
                "published": meta[:10] if from_meta else melbourne_day(l["createdAt"]),
                "supplier": re.sub(r"^\s*\d+\s*:\s*", "", ((l.get("supplier") or {}).get("value") or "")).strip(),  # "52908 : Pankaj" -> "Pankaj"
                "disc": ((l.get("disc") or {}).get("value") or "").strip().lower() in ("yes", "true", "1"),
                "cols": [], "fromMeta": from_meta, "migrated": migrated, "variants": {},
            }
            order.append(l["id"])
    for l in prod_lines:
        if "/Collection/" in l.get("id", "") and l.get("__parentId") in products:
            t = (l.get("title") or "").strip()
            if t and t not in products[l["__parentId"]]["cols"]:
                products[l["__parentId"]]["cols"].append(t)
        if "/ProductVariant/" in l.get("id", "") and l.get("__parentId") in products:
            p = products[l["__parentId"]]
            key = l["title"].strip().lower()
            cur = p["variants"].setdefault(key, [l["title"], 0, 0, "", 0, [], []])   # title, stock, sold, last sold day, sold in last 30 days, barcodes (for the scan box)
            vid = num(l["id"])
            cur[1] += int(l.get("inventoryQuantity") or 0)
            cur[2] += variant_sold.get(vid, 0)
            cur[3] = max(cur[3], variant_last.get(vid, ""))
            cur[4] += variant_30.get(vid, 0)
            if vid and str(vid) not in cur[6]:
                cur[6].append(str(vid))   # Shopify variant ids (long-press Stock tile edits stock)
            bc = (l.get("barcode") or "").strip()
            if bc and bc not in cur[5]:
                cur[5].append(bc)

    out = []
    for gid in order:
        p = products[gid]
        sales = product_sold.get(p["id"], 0)
        if sales <= 0:
            continue      # nothing ever sold: no days-to-sell, nothing to restock
        out.append({"id": p["id"], "title": p["title"], "image": p["image"], "url": p["url"], "published": p["published"],
                    "supplier": p["supplier"], "sales": sales, "last": product_last.get(p["id"], ""), "sold30": product_30.get(p["id"], 0),
                    "disc": p["disc"], "cols": sorted(p["cols"]), "variants": list(p["variants"].values())})
    sync_product_cols(products)
    no_meta = sum(1 for p in products.values() if p["migrated"] and not p["fromMeta"])

    now = dt.datetime.now(SYD)
    updated = now.strftime("%d %b %Y, %H:%M")
    data = {"generatedAt": now.isoformat(),
            "source": f"Shopify · {len(products)} active products ({len(out)} with sales) · {lines:,} order lines, full history",
            "products": out, "suppliers": sorted(choices, key=str.lower)}
    page = open(os.path.join(pv.ROOT, "tools", "restock_plan_template.html"), encoding="utf-8").read()
    assert page.count("__DATA__") == 1
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))

    oos = sum(1 for p in out for v in p["variants"] if v[1] <= 0 and v[2] > 0 and not p["disc"])
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
