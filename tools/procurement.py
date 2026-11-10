"""Build the encrypted Procurement report for the Indifeels dashboard (Stock Management).

What to buy: demand vs stock per collection.
  * Demand  = Shopify units sold in the last 12 months (by size and colour) + search volume from
              tools/procurement_demand.json (Semrush AU; more sources can be added to that file).
  * Stock   = on-hand units of active products (all locations), by size and colour.
Per collection it ships raw aggregates; the page does the maths (cover-days slider, size thresholds,
80% coverage, colour spread) so the sliders are live.

Colour: the variant's Colour/Color option, else the first colour word in the product title. Size: the Size option.
Needs read_products, read_orders, read_all_orders on SHOPIFY_TOKEN (same as the Restock Planner).

Also "Introduced vs cleared" (flow_aggregate): eligible vs not eligible products by real published month and real sale month,
by Australian financial year with a month drill-down. Eligible = Restock Planner rule (days since published / units sold < 50).
Needs one more bulk query (all products) and the line sale value on the orders query.

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

# display name, Shopify collection title (case-insensitive), Semrush search terms (monthly AU volume summed), Semrush colour-type key
COLLECTIONS = [
    ("Kurta Pajama", "Kurta Pajama", ["kurta pajama", "kurta pajama for men", "kurta for men", "mens kurta", "pathani kurta"], "kurta pajama"),
    ("Kurti for Women", "Kurti For Women", ["kurti", "kurti for women"], "kurti"),
    ("Anarkali Dress", "Anarkali Dress", ["anarkali", "anarkali dress", "anarkali suit"], "anarkali"),
    ("Suits", "Suits", ["punjabi suit", "salwar suit", "punjabi suit for women", "patiala suit"], "punjabi suit"),
    ("Top + Bottom Set", "Top+Bottom Set", ["kurti pant set", "kurta set for women"], None),
    ("Lehenga", "Lehenga", ["lehenga", "lehenga choli", "bridal lehenga", "designer lehenga", "lehenga online"], "lehenga"),
    ("Sarees", "Sarees", ["saree", "silk saree", "saree online", "cotton saree", "party wear saree"], "saree"),
    ("Saree Blouses", "Saree Blouses", ["saree blouse"], None),
    ("Nehru Jacket", "Nehru Jacket", ["nehru jacket", "nehru jacket for men"], None),
    ("Bottom Only", "Bottom Only", ["churidar", "dhoti pants"], None),
    ("Dupatta / Phulkari", "Dupatta/ Phulkari", ["dupatta"], None),
    ("Pocket Square", "Pocket Square", ["pocket square"], None),
    ("Women Footwear", "Women Footwear", ["indian shoes", "juttis", "mojari", "punjabi juttis", "kolhapuri chappal"], None),
    ("Footwear", "Footwear", [], None),
    ("Kids", "Kids", ["kids kurta", "kids lehenga", "kids kurta pajama", "boys kurta pajama", "girls lehenga", "kids ethnic wear"], None),
    ("Bangles", "Bangles", ["bangles", "bridal bangles", "glass bangles", "kada bangles"], None),
    ("Earrings", "Earrings", ["indian earrings", "jhumka earrings", "jhumka"], None),
    ("Necklace", "Necklace", ["indian necklace", "kundan necklace", "indian necklace set"], None),
    ("Anklets", "Anklets", ["anklet", "payal"], None),
    ("Rings", "Rings", [], None),
    ("Oxidised Jewellery", "Oxidised Jewellery", ["oxidised jewellery"], None),
    ("Maang Tikka Sets", "Maang Tikka Earrings Set", ["maang tikka"], None),
    ("Rakhi", "Rakhi", ["rakhi"], None),
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
  id title onlineStoreUrl featuredImage{ url }
  collections{ edges{ node{ id title } } }
  variants{ edges{ node{ id title inventoryQuantity selectedOptions{ name value } } } } } } } }"""
# same lines as the Restock Planner plus each line's sale value (after line discounts), for the introduced-vs-cleared view
ORDERS = """{ orders{ edges{ node{ id cancelledAt processedAt lineItems{ edges{ node{ id quantity title variantTitle variant{ id } product{ id }
  discountedTotalSet{ shopMoney{ amount } } } } } } } } }"""
# every product that was ever on the site (active + archived; drafts never launched), with the real published date and stock/price
FLOW_PRODUCTS = """{ products{ edges{ node{ id status createdAt
  metafield(namespace:"custom", key:"published_date_old"){ value }
  disc: metafield(namespace:"custom", key:"discountinued"){ value }
  sup: metafield(namespace:"custom", key:"supplier_name"){ value }
  variants{ edges{ node{ id inventoryQuantity price } } } } } } }"""

# Introduced vs cleared. Eligibility = the Restock Planner's "D.U new" rule: days on market / units sold < 50, where the clock
# stops at the last sale once the product is sold out or discontinued (instead of running to today).
FLOW_TEST_DAYS = 30      # published in the last 30 days = still in testing: left out of the graphs and totals
FLOW_MAX_DTS = 50        # same as MAX_PRODUCT_DTS in tools/restock_plan_template.html


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
            products[l["id"]] = {"id": rp.num(l["id"]), "title": l.get("title") or "", "cols": set(), "variants": {},
                                 "img": ((l.get("featuredImage") or {}).get("url")) or "", "url": l.get("onlineStoreUrl") or ""}
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
    for disp, title, terms, sem_col in COLLECTIONS:
        members = [P for P in products.values() if title.lower() in P["cols"]]
        if not members:
            continue
        sizes, colours = {}, {}
        sold_total = stock_total = 0
        designs_in = designs_sold = 0
        design_sales, dead = [], []
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
            elif p_stock > 0:
                dead.append((p_stock, P))
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
            "search": sum(int((demand.get("terms") or {}).get(t, 0)) for t in terms), "terms": [[t, int((demand.get("terms") or {}).get(t, 0))] for t in terms],
            "dead": {"designs": len(dead), "units": sum(x[0] for x in dead),
                     "items": [{"t": P["title"], "s": q, "i": (P["img"] + ("&" if "?" in P["img"] else "?") + "width=160") if P["img"] else "", "u": P["url"]}
                               for q, P in sorted(dead, key=lambda x: -x[0])[:10]]},
            "sizes": sorted(sizes.values(), key=lambda s: size_rank(s["size"])),
            "colours": sorted(colours.values(), key=lambda c: -c["sold"]),
            "colSearch": search,
        })
    return out, {"lines": lines, "unmapped_units": unmapped, "products": len(products)}


def fy_label(month):
    """'2025-08' -> 'FY26': Australian financial year (1 Jul to 30 Jun), named by the year it ends."""
    y, m = int(month[:4]), int(month[5:7])
    return "FY%02d" % ((y + 1 if m >= 7 else y) % 100)


def flow_aggregate(prod_lines, order_lines, today=None):
    """Products introduced vs cleared per month, eligible vs not eligible. Real data only.

    Introduced = products by the month of their real published date (published_date_old for products migrated from
    WooCommerce, else the created date). Cleared = real sale date (processedAt) of each order line: units, and the actual
    sale value after line discounts. Still on shelf = today's stock units and value (at sale price) grouped by the month the
    product was published, plus units those products have sold to date (for sell-through). Shopify does not store the
    original buy quantity, so there is deliberately NO historical stock-level or "value introduced" series.
    Group (today's status, applied to the whole history): g='e' eligible, 'n' not eligible (no sales, or 50+ days per unit;
    days on market stop at the last sale when the product is sold out or discontinued, same as D.U new in the Restock Planner),
    't' testing (published under 30 days ago: shown on a tile only), 'x' migrated with no published date (never guessed).
    Parked / discontinued do not matter here."""
    today = today or dt.datetime.now(rp.MEL).date()
    products, drafts = {}, 0
    for l in prod_lines:
        if "/Product/" not in l.get("id", "") or "__parentId" in l:
            continue
        status = (l.get("status") or "").upper()
        if status == "DRAFT":
            drafts += 1
            continue
        created = dt.datetime.fromisoformat(l["createdAt"].replace("Z", "+00:00"))
        meta = ((l.get("metafield") or {}).get("value") or "")
        if created < rp.MIGRATION_CUTOFF:
            published = meta[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", meta) else ""
        else:
            published = rp.melbourne_day(l["createdAt"])
        products[l["id"]] = {"id": rp.num(l["id"]), "published": published, "stock": 0, "value": 0.0, "prices": [],
                             "sold": 0, "monthly": {}, "last": "", "nvar": 0, "active": status == "ACTIVE",
                             "sup": ((l.get("sup") or {}).get("value") or "").strip().strip('[]"').strip(),
                             "disc": ((l.get("disc") or {}).get("value") or "").strip().lower() in ("yes", "true", "1")}
    for l in prod_lines:
        P = products.get(l.get("__parentId"))
        if P and "/ProductVariant/" in l.get("id", ""):
            q, price = max(0, int(l.get("inventoryQuantity") or 0)), float(l.get("price") or 0)
            P["nvar"] += 1
            P["stock"] += q
            P["value"] += q * price
            if price > 0:
                P["prices"].append(price)

    cancelled = {l["id"] for l in order_lines if "/Order/" in l.get("id", "") and l.get("cancelledAt")}
    placed = {l["id"]: rp.melbourne_day(l["processedAt"]) for l in order_lines if "/Order/" in l.get("id", "") and l.get("processedAt")}
    by_pid = {P["id"]: P for P in products.values()}
    lines = unmapped_units = 0
    unmapped_rev = 0.0
    for l in order_lines:
        if "/LineItem/" not in l.get("id", "") or l.get("__parentId") in cancelled:
            continue
        lines += 1
        q = int(l.get("quantity") or 0)
        rev = float((((l.get("discountedTotalSet") or {}).get("shopMoney")) or {}).get("amount") or 0)
        day = placed.get(l.get("__parentId"), "")
        P = by_pid.get(rp.num((l.get("product") or {}).get("id")))
        if not P or not day:
            unmapped_units += q       # custom items, POS items and products deleted from the store
            unmapped_rev += rev
            continue
        P["sold"] += q
        if day > P["last"]:
            P["last"] = day
        cur = P["monthly"].setdefault(day[:7], [0, 0.0])
        cur[0] += q
        cur[1] += rev
    if lines < 50:
        raise RuntimeError(f"Only {lines} order lines came back: refusing to publish incomplete sales history")

    months = {}
    snap = {g: {"products": 0, "stocked": 0, "units": 0, "value": 0.0} for g in "entx"}
    slot = lambda m: months.setdefault(m, {g: [0, 0, 0.0, 0, 0.0] for g in "en"})   # intro products, sold units (by sale month), sold value (by sale month), shelf units, shelf value
    cohort = lambda m: cohorts.setdefault(m, {g: [0, 0] for g in "en"})            # products published that month: units sold to date, products still stocked
    cohorts = {}
    sup = {}
    supcov = {k: {"has": 0, "missing": 0, "hasStock": 0, "missingStock": 0} for k in ("active", "other")}
    for P in products.values():
        avg = sum(P["prices"]) / len(P["prices"]) if P["prices"] else 0.0
        if not P["published"]:
            g = "x"
        else:
            days = max(0, (today - dt.date.fromisoformat(P["published"])).days)
            # D.U new: clock stops at the last sale once sold out or discontinued; at least 1 day (same as the planner)
            end = today
            if (P["disc"] or P["stock"] <= 0) and P["last"]:
                end = min(today, dt.date.fromisoformat(P["last"]))
            days_n = max(1, (end - dt.date.fromisoformat(P["published"])).days)
            g = "t" if days < FLOW_TEST_DAYS else ("e" if P["sold"] > 0 and days_n / P["sold"] < FLOW_MAX_DTS else "n")
        if P["sup"] and g in "en":
            u = sup.setdefault(P["sup"], {"products": 0, "variants": 0, "sold": 0, "days": 0, "elig": 0, "stockUnits": 0, "stockValue": 0.0, "saleValue": 0.0})
            u["products"] += 1
            u["variants"] += P["nvar"]
            u["sold"] += P["sold"]
            u["days"] += days_n
            u["elig"] += 1 if g == "e" else 0
            u["stockUnits"] += P["stock"]
            u["stockValue"] += P["value"]
            u["saleValue"] += sum(v[1] for v in P["monthly"].values())
        cov = supcov["active" if P["active"] else "other"]
        cov["has" if P["sup"] else "missing"] += 1
        if P["stock"] > 0:
            cov["hasStock" if P["sup"] else "missingStock"] += 1
        s = snap[g]
        s["products"] += 1
        s["stocked"] += 1 if P["stock"] > 0 else 0
        s["units"] += P["stock"]
        s["value"] += P["value"]
        if g in "en":
            a = slot(P["published"][:7])[g]
            a[0] += 1
            a[3] += P["stock"]
            a[4] += P["value"]
            c = cohort(P["published"][:7])[g]
            c[0] += P["sold"]
            c[1] += 1 if P["stock"] > 0 else 0
            for m, (u, rev) in P["monthly"].items():
                b = slot(m)[g]
                b[1] += u
                b[2] += rev
    if not months:
        return None
    last = max(max(months), today.strftime("%Y-%m"))
    keys, y, m = [], int(min(months)[:4]), int(min(months)[5:7])
    while True:
        k = "%04d-%02d" % (y, m)
        keys.append(k)
        if k >= last:
            break
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    out = {"asOf": today.isoformat(), "months": keys, "testDays": FLOW_TEST_DAYS, "maxDts": FLOW_MAX_DTS,
           "drafts": drafts, "unmapped": {"units": unmapped_units, "value": round(unmapped_rev)}}
    for g in "en":
        out[g] = {n: [round(months.get(k, {}).get(g, [0] * 5)[i]) for k in keys] for i, n in enumerate(("ic", "su", "sv", "ku", "kv"))}
        out[g]["pu"] = [round(cohorts.get(k, {}).get(g, [0, 0])[0]) for k in keys]       # units sold to date by products published that month
        out[g]["ks"] = [round(cohorts.get(k, {}).get(g, [0, 0])[1]) for k in keys]       # of those products, how many still have stock
    rows = []
    for name, u in sup.items():
        rows.append({"name": name, "products": u["products"], "variants": u["variants"], "sold": u["sold"],
                     "dts": round(u["days"] / u["sold"], 1) if u["sold"] else None,
                     "upp": round(u["sold"] / u["products"], 2), "upv": round(u["sold"] / u["variants"], 2) if u["variants"] else 0,
                     "elig": round(100 * u["elig"] / u["products"]), "stockUnits": u["stockUnits"],
                     "stockValue": round(u["stockValue"]), "saleValue": round(u["saleValue"])})
    out["sup"] = {"cov": supcov, "rows": rows}
    out["snap"] = {g: {k: (round(v) if k == "value" else v) for k, v in s.items()} for g, s in snap.items()}
    return out


def build_page(cols, info, demand, now, flow=None):
    data = {"generatedAt": now.isoformat(), "windowDays": WINDOW_DAYS, "collections": cols, "flow": flow,
            "source": f"Shopify · {info['products']:,} active products · {info['lines']:,} order lines, last {WINDOW_DAYS} days · "
                      f"search: {demand.get('source', 'none')} ({demand.get('fetched', '')})"}
    page = open(os.path.join(pv.ROOT, "tools", "procurement_template.html"), encoding="utf-8").read()
    assert page.count("__DATA__") == 1
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    updated = now.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    dead = sum(c["dead"]["units"] for c in cols)
    meta = {"updated": updated, "stats": [[str(len(cols)), "collections tracked"], [f"{dead:,}", "units of dead stock"]]}
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
    flow = None
    try:   # the introduced-vs-cleared view must never take the rest of the report down
        flow = flow_aggregate(rp.bulk(FLOW_PRODUCTS, "flow products"), order_lines)
    except Exception as exc:
        print("introduced-vs-cleared view skipped:", str(exc)[:300])
    if flow and flow.get("sup"):   # counts for the owner to read in the run log
        print("SUPPLIER COVERAGE", json.dumps(flow["sup"]["cov"]))
        for x in sorted(flow["sup"]["rows"], key=lambda x: (x["dts"] is None, x["dts"] or 0)):
            print("SUPPLIER", json.dumps(x))
    page, meta = build_page(cols, info, demand, dt.datetime.now(rp.SYD), flow)
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
        today = dt.date.fromisoformat(fx.get("today", "2026-10-30"))
        cols, info = aggregate(fx["products"], fx["orders"], demand, today=today)
        flow = flow_aggregate(fx["flow_products"], fx["orders"], today=today) if fx.get("flow_products") else None
        page, meta = build_page(cols, info, demand, dt.datetime.now(rp.SYD), flow)
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
