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

PRODUCTS = """{ products(query:"status:active"){ edges{ node{
  id title featuredImage{ url }
  collections{ edges{ node{ id title } } }
  variants{ edges{ node{ id title barcode inventoryItem{ id inventoryLevels{ edges{ node{ location{ id name } quantities(names:["available"]){ quantity } } } } } } } } } } } }"""


def num(gid):
    return gid.rsplit("/", 1)[-1] if gid else ""


def build():
    lines = rp.bulk(PRODUCTS, "stock take products")
    products, variants, items, locations = {}, {}, {}, {}
    for l in lines:
        gid = l.get("id", "")
        if "/Product/" in gid and "__parentId" not in l:
            products[gid] = {"id": num(gid), "title": l.get("title", ""), "image": ((l.get("featuredImage") or {}).get("url")) or "",
                             "cols": [], "variants": []}
    for l in lines:
        gid = l.get("id", "")
        par = l.get("__parentId")
        if "/Collection/" in gid and par in products:
            t = (l.get("title") or "").strip()
            if t and not any(n in t.lower() for n in NOISE) and t not in products[par]["cols"]:
                products[par]["cols"].append(t)
        elif "/ProductVariant/" in gid and par in products:
            v = {"vid": num(gid), "t": l.get("title", ""), "bc": [b for b in [(l.get("barcode") or "").strip()] if b], "q": {}}
            products[par]["variants"].append(v)
            variants[gid] = v
            it = (l.get("inventoryItem") or {}).get("id")
            if it:
                items[it] = v
    for l in lines:
        if "/InventoryLevel/" not in l.get("id", ""):
            continue
        v = variants.get(l.get("__parentId")) or items.get(l.get("__parentId"))
        loc = l.get("location") or {}
        if not v or not loc.get("id"):
            continue
        lid = num(loc["id"])
        locations[lid] = loc.get("name") or lid
        qs = l.get("quantities") or []
        v["q"][lid] = int(qs[0]["quantity"]) if qs else 0

    out = [p for p in products.values() if p["variants"]]
    out.sort(key=lambda p: p["title"].lower())
    nvar = sum(len(p["variants"]) for p in out)
    if len(out) < 20 or nvar < 50:
        raise RuntimeError(f"Only {len(out)} products / {nvar} variants came back: refusing to publish an incomplete stock list")
    if not locations:
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
