"""Build the encrypted Procurement report for the Indifeels dashboard (Stock Management).

What to buy: demand vs stock per collection.
  * Demand  = Shopify units sold in the last 12 months (by size and colour) + search volume from
              tools/procurement_demand.json (Semrush AU; more sources can be added to that file).
  * Stock   = on-hand units of active products (all locations), by size and colour.
Per collection it ships raw aggregates; the page does the maths (cover-days slider, size thresholds,
80% coverage, colour spread) so the sliders are live.

Colour: the variant's Colour/Color option, else the first colour word in the product title. Size: the Size option.
Needs read_products, read_orders, read_all_orders on SHOPIFY_TOKEN (same as the Restock Planner).

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY
Writes: r/procurement.bin, r/procurement.meta.bin, r/status.json
Offline test: python3 tools/procurement.py --fixture lines.json --out DIR   (no Shopify, no key, no status)
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv
import restock_plan as rp

RID = "procurement"
DEMAND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "procurement_demand.json")
WINDOW_DAYS = 365

# display name, Shopify collection title (case-insensitive), Semrush category key, Semrush colour-type key
COLLECTIONS = [
    ("Kurta Pajama", "Kurta Pajama", "kurta pajama", "kurta pajama"),
    ("Kurti for Women", "Kurti For Women", "kurti", "kurti"),
    ("Short Top Kurti", "SHORT TOP KURTI", "kurti", "kurti"),
    ("Short Kurta for Men", "Short Kurta For Men", "kurta pajama for men", "kurta pajama"),
    ("Anarkali Dress", "Anarkali Dress", "anarkali", "anarkali"),
    ("Suits", "Suits", "punjabi suit", "punjabi suit"),
    ("Top + Bottom Set", "Top+Bottom Set", "kurti pant set", None),
    ("Lehenga", "Lehenga", "lehenga", "lehenga"),
    ("Sarees", "Sarees", "saree", "saree"),
    ("Saree Blouses", "Saree Blouses", "saree blouse", None),
    ("Nehru Jacket", "Nehru Jacket", "nehru jacket", None),
    ("Bottom Only", "Bottom Only", None, None),
    ("Dupatta / Phulkari", "Dupatta/ Phulkari", "dupatta", None),
    ("Pocket Square", "Pocket Square", None, None),
    ("Women Footwear", "Women Footwear", "indian shoes", None),
    ("Footwear", "Footwear", "indian shoes", None),
    ("Kids", "Kids", "kids ethnic wear", None),
    ("Bangles", "Bangles", "bangles", None),
    ("Earrings", "Earrings", "indian jewellery", None),
    ("Necklace", "Necklace", "indian jewellery", None),
    ("Rings", "Rings", None, None),
    ("Oxidised Jewellery", "Oxidised Jewellery", "oxidised jewellery", None),
    ("Maang Tikka Sets", "Maang Tikka Earrings Set", "maang tikka", None),
]

# longest phrases first so "navy blue" wins over "blue"
COLOUR_WORDS = [
    ("off white", "White"), ("off-white", "White"), ("navy blue", "Blue"), ("sky blue", "Blue"), ("royal blue", "Blue"),
    ("light blue", "Blue"), ("dark blue", "Blue"), ("rani pink", "Pink"), ("hot pink", "Pink"), ("baby pink", "Pink"),
    ("yellow gold", "Gold"), ("rose gold", "Gold"),
    ("black", "Black"), ("white", "White"), ("ivory", "White"), ("cream", "Beige"), ("beige", "Beige"), ("blue", "Blue"),
    ("navy", "Blue"), ("red", "Red"), ("maroon", "Maroon"), ("wine", "Maroon"), ("burgundy", "Maroon"), ("green", "Green"),
    ("mehendi", "Green"), ("olive", "Green"), ("yellow", "Yellow"), ("mustard", "Mustard"), ("orange", "Orange"),
    ("pink", "Pink"), ("peach", "Peach"), ("purple", "Purple"), ("lavender", "Purple"), ("grey", "Grey"), ("gray", "Grey"),
    ("brown", "Brown"), ("gold", "Gold"), ("silver", "Silver"), ("multi", "Multicolour"), ("turquoise", "Teal"), ("teal", "Teal"),
]
SEARCH_COLOUR = {"navy blue": "Blue", "black": "Black", "white": "White", "blue": "Blue", "red": "Red", "green": "Green",
                 "maroon": "Maroon", "yellow": "Yellow", "mustard": "Mustard", "beige": "Beige", "grey": "Grey", "pink": "Pink"}

PRODUCTS = """{ products(query:"status:active"){ edges{ node{
  id title
  collections{ edges{ node{ id title } } }
  variants{ edges{ node{ id title inventoryQuantity selectedOptions{ name value } } } } } } } }"""
ORDERS = rp.ORDERS


def norm_colour(text):
    t = " " + re.sub(r"[^a-z ]+", " ", (text or "").lower()) + " "
    best = None
    for word, label in COLOUR_WORDS:
        i = t.find(" " + word)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, label)
    return best[1] if best else None


def size_rank(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*$", s or "")
    if m:
        return (0, float(m.group(1)), s)
    return (1, 0, s or "")


def variant_attrs(title, options):
    """(size, colour) for one variant"""
    size = colour = None
    for o in options:
        n = (o.get("name") or "").lower()
        v = (o.get("value") or "").strip()
        if "size" in n:
            size = v
        elif n in ("colour", "color"):
            colour = norm_colour(v) or (v.title() if v else None)
    if not size:
        only = [o for o in options if (o.get("value") or "").strip().lower() not in ("default title", "")]
        size = "One size" if len(only) <= 1 else None
    if size and size.lower() in ("default title", "free size", "freesize", "one size", "free"):
        size = "One size"
    return size, colour


def aggregate(prod_lines, order_lines, demand, today=None):
    today = today or dt.datetime.now(rp.MEL).date()
    since = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()

    products = {}
    for l in prod_lines:
        if "/Product/" in l.get("id", "") and "__parentId" not in l:
            products[l["id"]] = {"id": rp.num(l["id"]), "title": l.get("title") or "", "cols": set(), "variants": {}}
    for l in prod_lines:
        pid = l.get("__parentId")
        if pid not in products:
            continue
        if "/Collection/" in l.get("id", ""):
            products[pid]["cols"].add((l.get("title") or "").strip().lower())
        elif "/ProductVariant/" in l.get("id", ""):
            P = products[pid]
            size, colour = variant_attrs(l.get("title"), l.get("selectedOptions") or [])
            colour = colour or norm_colour(P["title"]) or "Unspecified"
            P["variants"][rp.num(l["id"])] = {"title": (l.get("title") or "").strip().lower(), "size": size,
                                               "colour": colour, "stock": max(0, int(l.get("inventoryQuantity") or 0)), "sold": 0}

    cancelled = {l["id"] for l in order_lines if "/Order/" in l.get("id", "") and l.get("cancelledAt")}
    placed = {l["id"]: rp.melbourne_day(l["processedAt"]) for l in order_lines if "/Order/" in l.get("id", "") and l.get("processedAt")}
    by_pid = {P["id"]: P for P in products.values()}
    lines = unmapped = 0
    for l in order_lines:
        if "/LineItem/" not in l.get("id", "") or l.get("__parentId") in cancelled:
            continue
        if placed.get(l.get("__parentId"), "") < since:
            continue
        lines += 1
        q = int(l.get("quantity") or 0)
        vid, pid = rp.num((l.get("variant") or {}).get("id")), rp.num((l.get("product") or {}).get("id"))
        P = by_pid.get(pid)
        if not P:
            unmapped += q
            continue
        if vid in P["variants"]:
            P["variants"][vid]["sold"] += q
            continue
        # migrated order that lost its variant: match the size text, else keep it at product level only
        key = rp.size_key(l)
        tails = {v["title"]: vid2 for vid2, v in P["variants"].items()}
        hit = rp.match_variant(tails, key)
        if hit:
            P["variants"][tails[hit]]["sold"] += q
        else:
            P.setdefault("loose", 0)
            P["loose"] += q
            unmapped += q
    if lines < 50:
        raise RuntimeError(f"Only {lines} order lines in the last {WINDOW_DAYS} days: refusing to publish incomplete sales history")

    out = []
    for disp, title, sem_cat, sem_col in COLLECTIONS:
        members = [P for P in products.values() if title.lower() in P["cols"]]
        if not members:
            continue
        sizes, colours = {}, {}
        sold_total = stock_total = 0
        designs_in = designs_sold = 0
        design_sales = []
        for P in members:
            vs = list(P["variants"].values())
            p_sold = sum(v["sold"] for v in vs) + P.get("loose", 0)
            p_stock = sum(v["stock"] for v in vs)
            sold_total += p_sold
            stock_total += p_stock
            designs_in += 1 if p_stock > 0 else 0
            designs_sold += 1 if p_sold > 0 else 0
            if p_sold > 0:
                design_sales.append(p_sold)
            seen_s, seen_c = set(), set()
            for v in vs:
                if v["size"]:
                    s = sizes.setdefault(v["size"], {"size": v["size"], "sold": 0, "stock": 0, "designs": 0})
                    s["sold"] += v["sold"]
                    s["stock"] += v["stock"]
                    if v["stock"] > 0 and v["size"] not in seen_s:
                        s["designs"] += 1
                        seen_s.add(v["size"])
                c = colours.setdefault(v["colour"], {"colour": v["colour"], "sold": 0, "stock": 0, "designs": 0})
                c["sold"] += v["sold"]
                c["stock"] += v["stock"]
                if v["stock"] > 0 and v["colour"] not in seen_c:
                    c["designs"] += 1
                    seen_c.add(v["colour"])
        design_sales.sort(reverse=True)
        run, n80 = 0, 0
        for x in design_sales:
            n80 += 1
            run += x
            if run >= 0.8 * sum(design_sales):
                break
        search = {}
        if sem_col:
            for k, v in (demand.get("colour_by_type", {}).get(sem_col) or {}).items():
                lab = SEARCH_COLOUR.get(k)
                if lab:
                    search[lab] = search.get(lab, 0) + int(v)
        out.append({
            "name": disp, "designs": len(members), "designsIn": designs_in, "designsSold": designs_sold, "n80": n80,
            "sold": sold_total, "stock": stock_total,
            "catSearch": int((demand.get("category") or {}).get(sem_cat, 0)) if sem_cat else None,
            "catTerm": sem_cat,
            "sizes": sorted(sizes.values(), key=lambda s: size_rank(s["size"])),
            "colours": sorted(colours.values(), key=lambda c: -c["sold"]),
            "search": search,
        })
    return out, {"lines": lines, "unmapped_units": unmapped, "products": len(products)}


def build_page(cols, info, demand, now):
    data = {"generatedAt": now.isoformat(), "windowDays": WINDOW_DAYS, "collections": cols,
            "source": f"Shopify · {info['products']:,} active products · {info['lines']:,} order lines, last {WINDOW_DAYS} days · "
                      f"search: {demand.get('source', 'none')} ({demand.get('fetched', '')})"}
    page = open(os.path.join(pv.ROOT, "tools", "procurement_template.html"), encoding="utf-8").read()
    assert page.count("__DATA__") == 1
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    updated = now.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    short = sum(1 for c in cols if c["sold"] and c["stock"] < c["sold"] / WINDOW_DAYS * 90)
    meta = {"updated": updated, "stats": [[str(len(cols)), "collections tracked"], [str(short), "under 90 days of stock"]]}
    return page, meta


def load_demand():
    try:
        return json.load(open(DEMAND_FILE, encoding="utf-8"))
    except Exception:
        return {}


def build():
    rp.require_scopes()
    prod_lines = rp.bulk(PRODUCTS, "products")
    order_lines = rp.bulk(ORDERS, "orders")
    demand = load_demand()
    cols, info = aggregate(prod_lines, order_lines, demand)
    page, meta = build_page(cols, info, demand, dt.datetime.now(rp.SYD))
    key = os.environ["STOCK_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"collections": len(cols), **info, "page_kb": round(len(page) / 1024)}))


if __name__ == "__main__":
    pv.RID = RID
    if "--fixture" in sys.argv:
        fx = json.load(open(sys.argv[sys.argv.index("--fixture") + 1]))
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
        demand = load_demand()
        cols, info = aggregate(fx["products"], fx["orders"], demand, today=dt.date.fromisoformat(fx.get("today", "2026-10-30")))
        page, meta = build_page(cols, info, demand, dt.datetime.now(rp.SYD))
        open(os.path.join(out, "procurement.html"), "w", encoding="utf-8").write(page)
        print(json.dumps({"info": info, "meta": meta}))
        sys.exit(0)
    try:
        build()
    except Exception as exc:
        try:
            pv.set_status(False, f"Procurement build failed: {str(exc)[:160]}")
        except Exception:
            pass
        raise
