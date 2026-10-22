"""Build the encrypted "Stock Take and Transfer" report for the Indifeels dashboard.

Page = tools/stock_take_template.html (Bulk transfer between Shopify locations + Stock take counting).
Data = every ACTIVE product: title, image, collections, and per variant: id, title (size), barcodes, available stock per location.
The page itself moves stock / saves counts through the hub (Supabase edge function restock-stock, table stock_takes).

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY
Writes: r/stock-take.bin, r/stock-take.meta.bin, r/status.json
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv  # gql, write_encrypted, set_status
import restock_plan as rp        # bulk() helper (waits for any running bulk operation, polls, downloads)

RID = "stock-take"
MEL = ZoneInfo("Australia/Melbourne")
NOISE = ("do not delete", "filter index", "all products", "home page", "frontpage")

PRODUCTS = """{ products(query:"status:active OR status:unlisted OR status:draft"){ edges{ node{
  id title handle status createdAt onlineStoreUrl featuredImage{ url }
  metafield(namespace:"shopify", key:"color-pattern"){ jsonValue }
  collections{ edges{ node{ id title } } }
  variants{ edges{ node{ id title barcode price inventoryItem{ id inventoryLevels{ edges{ node{ location{ id name } quantities(names:["available"]){ quantity } } } } } } } } } } } }"""


CHANNEL_HIDDEN = ("published_status:unpublished", "published_status:shop-72-hidden", "published_status:pos-hidden",
                  "published_status:google-hidden", "published_status:facebook-ads-hidden")   # Online Store, Shop, POS, Google & YouTube, Facebook & Instagram
IDS_ONLY = "query($after:String,$q:String!){ products(first:250,after:$after,query:$q){ pageInfo{hasNextPage endCursor} nodes{ id } } }"


def channels_off():
    """product id -> how many of the 5 sales channels it is NOT published to (published_status filters only need read_products)."""
    off = {}
    for flt in CHANNEL_HIDDEN:
        after = None
        while True:
            d = pv.gql(IDS_ONLY, {"after": after, "q": "(status:active OR status:unlisted OR status:draft) " + flt})["data"]["products"]
            for n in d["nodes"]:
                pid = n["id"].rsplit("/", 1)[-1]
                off[pid] = off.get(pid, 0) + 1
            if not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]
    return off


def menu_collections():
    """Main collection pages = the ones linked from the store menus (tools/stock_take_collections.json).
    Tag-driven SEO/city collections that no menu links to are left out."""
    with open(os.path.join(pv.ROOT, "tools", "stock_take_collections.json")) as f:
        return set(json.load(f)["ids"])


COLOR_DEFS = "query($after:String){ metaobjects(type:\"shopify--color-pattern\", first:100, after:$after){ pageInfo{hasNextPage endCursor} nodes{ id displayName fields{ key value } } } }"


def color_labels():
    """metaobject gid -> colour name (e.g. Beige). Empty when the token cannot read metaobjects: labels then just skip the colour."""
    out, after = {}, None
    try:
        while True:
            d = pv.gql(COLOR_DEFS, {"after": after})["data"]["metaobjects"]
            for n in d["nodes"]:
                f = {x["key"]: x["value"] for x in n["fields"]}
                out[n["id"]] = (f.get("label") or n["displayName"] or "").strip()
            if not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]
    except Exception as exc:
        print("colour names skipped:", exc)
    return out


def num(gid):
    return gid.rsplit("/", 1)[-1] if gid else ""


def build():
    main_cols = menu_collections()
    print("menu collections:", len(main_cols))
    if len(main_cols) < 10:
        raise RuntimeError(f"Only {len(main_cols)} menu collections found: refusing to guess which collections are main ones")
    lines = rp.bulk(PRODUCTS, "stock take products")
    cnames = color_labels()
    products, variants, items, locations = {}, {}, {}, {}
    for l in lines:
        gid = l.get("id", "")
        if "/Product/" in gid and "__parentId" not in l:
            products[gid] = {"id": num(gid), "title": l.get("title", ""), "image": ((l.get("featuredImage") or {}).get("url")) or "",
                             "h": l.get("handle") or "", "st": l.get("status") or "", "ca": l.get("createdAt") or "",
                             "url": l.get("onlineStoreUrl") or (("https://indifeels.com/products/" + l["handle"]) if l.get("handle") else ""),
                             "cols": [], "variants": [],
                             "colors": [cnames[g] for g in ((l.get("metafield") or {}).get("jsonValue") or []) if cnames.get(g)]}
    for l in lines:
        gid = l.get("id", "")
        par = l.get("__parentId")
        if "/Collection/" in gid and par in products and gid in main_cols:
            t = (l.get("title") or "").strip()
            if t and not any(n in t.lower() for n in NOISE) and t not in products[par]["cols"]:
                products[par]["cols"].append(t)
        elif "/ProductVariant/" in gid and par in products:
            v = {"vid": num(gid), "t": l.get("title", ""), "bc": [b for b in [(l.get("barcode") or "").strip()] if b], "pr": str(l.get("price") or ""), "q": {}}
            products[par]["variants"].append(v)
            variants[gid] = v
            it = (l.get("inventoryItem") or {}).get("id")
            if it:
                items[it] = v
    for l in lines:
        if "/InventoryItem/" in l.get("id", "") and l.get("__parentId") in variants:
            items[l["id"]] = variants[l["__parentId"]]
    for l in lines:
        if "location" not in l or "quantities" not in l:
            continue
        v = variants.get(l.get("__parentId")) or items.get(l.get("__parentId"))
        loc = l.get("location") or {}
        if not v or not loc.get("id"):
            continue
        lid = num(loc["id"])
        locations[lid] = loc.get("name") or lid
        qs = l.get("quantities") or []
        v["q"][lid] = int(qs[0]["quantity"]) if qs else 0

    try:
        off = channels_off()
        for p in products.values():
            p["ch"] = max(0, 5 - off.get(p["id"], 0))
        print("channel counts for", len(off), "products with a channel off")
    except Exception as exc:      # channel numbers are a nice-to-have: never block the stock list on them
        print("channel counts skipped:", exc)
    out = [p for p in products.values() if p["variants"]]
    out.sort(key=lambda p: p["title"].lower())
    nvar = sum(len(p["variants"]) for p in out)
    if len(out) < 20 or nvar < 50:
        raise RuntimeError(f"Only {len(out)} products / {nvar} variants came back: refusing to publish an incomplete stock list")
    if not locations:
        from collections import Counter
        kinds = Counter(l.get("id", "?").split("/")[3] if l.get("id", "").count("/") >= 3 else "?" for l in lines)
        print("DIAG kinds:", dict(kinds))
        seen = set()
        for l in lines:
            k = l.get("id", "?").split("/")[3] if l.get("id", "").count("/") >= 3 else "?"
            if k not in seen and k != "Product":
                seen.add(k)
                print("DIAG sample", k, json.dumps(l)[:500])
        raise RuntimeError("No inventory locations came back (the token may need read_inventory / read_locations)")
    with_stock = sum(1 for p in out for v in p["variants"] if any(q > 0 for q in v["q"].values()))
    now = dt.datetime.now(MEL)
    data = {"generatedAt": now.isoformat(), "locations": [{"id": k, "name": n} for k, n in sorted(locations.items(), key=lambda x: x[1])], "products": out}
    page = open(os.path.join(pv.ROOT, "tools", "stock_take_template.html"), encoding="utf-8").read()
    assert page.count("__DATA__") == 1
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    meta = {"updated": now.strftime("%d %b %Y, %H:%M"), "stats": [[str(len(out)), "products"], [str(with_stock), "variants in stock"]], "warn": ""}
    key = os.environ["STOCK_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"products": len(out), "variants": nvar, "variants_in_stock": with_stock, "locations": len(locations), "page_kb": round(len(page) / 1024)}))


if __name__ == "__main__":
    pv.RID = RID
    try:
        build()
    except Exception as exc:
        pv.RID = RID
        try:
            pv.set_status(False, f"Stock Take build failed: {str(exc)[:160]}")
        except Exception:
            pass
        raise
