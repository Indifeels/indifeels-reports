"""Build the encrypted Profit Flow report (Sankey: sales -> GST -> product cost -> ads -> fixed costs -> net profit).

Per Melbourne day: card sales and cash sales (Shopify transactions, refunds netted, cancelled orders excluded),
Google Ads spend and Meta spend (Windsor). The page (tools/profit_flow_template.html) switches between Today /
This week (Mon-today) / This month with three tiles and redraws the Sankey. All cost rules live in CONFIG below.

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, WINDSOR_API_KEY, PROFIT_FLOW_KEY
Writes: r/profit-flow.bin, r/profit-flow.meta.bin, r/status.json
Offline preview: python3 tools/profit_flow.py --fixture data.json --out DIR  (data.json = {"orders":[...],"google":[{date,spend}],"meta":[{date,spend}]})
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RID = "profit-flow"
START = "2026-04-18"  # Shopify migration date; same start as the Cash Report
TZ = ZoneInfo("Australia/Melbourne")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profit_flow_template.html")
GOOGLE_ACCT = os.environ.get("WINDSOR_GOOGLE_ADS_ACCOUNT", "788-887-6041")
META_ACCT = os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990")

# Edit here. Monthly AUD costs are spread evenly per day of the month. amount None = not set yet (hidden on the chart).
CONFIG = {
    # Clearance plan for not-eligible stock (suggested sale prices on the product table)
    "clearance": {"horizon_months": 12, "max_discount": 0.25, "step": 0.05, "elasticity": 2.0, "rate_days": 90},
    "product_cost_pct": 0.32,      # of total sales; replace with real per-product cost later
    "gst_card_only": True,         # GST (1/11 of a GST-inclusive price) on card sales only; cash has no GST
    "fixed_monthly": [
        {"name": "Sunita", "amount": 300},
        {"name": "Google Ads mgmt", "amount": round(155 * 52 / 12, 2)},   # $155 per week
        {"name": "Facebook mgmt", "amount": round(15000 / 67, 2)},       # 15,000 INR / 67
        {"name": "SEO", "amount": 250},
        {"name": "SEMrush", "amount": 192},
        {"name": "Global Search Filter", "amount": 70},
        {"name": "Davy", "amount": 200},
        {"name": "Shopify plan", "amount": 56},
    ],
}

QUERY = """
query PF($after:String,$q:String!){
  orders(first:100,after:$after,query:$q,sortKey:PROCESSED_AT){
    pageInfo{hasNextPage endCursor}
    nodes{ name processedAt cancelledAt src:metafield(namespace:"custom",key:"order_source"){value}
      transactions(first:20){gateway kind status amountSet{shopMoney{amount}}} }
  }
}
"""


def fetch_orders(start):
    import product_visibility as pv
    q = f"processed_at:>={(dt.date.fromisoformat(start) - dt.timedelta(days=1)).isoformat()}"
    after, out = None, []
    while True:
        d = pv.gql(QUERY, {"after": after, "q": q})["data"]["orders"]
        out.extend(d["nodes"])
        if not d["pageInfo"]["hasNextPage"]:
            return out
        after = d["pageInfo"]["endCursor"]


def product_query():
    """Procurement's all-products query plus what the product table needs: title, page URL, picture, collections."""
    import procurement as pr
    q = pr.FLOW_PRODUCTS
    q = q.replace("variants{ edges{ node{ id inventoryQuantity price } } }", "variants{ edges{ node{ id inventoryQuantity price compareAtPrice } } }")
    return q.replace("{ products{ edges{ node{ id status createdAt",
                     "{ products{ edges{ node{ id status createdAt title onlineStoreUrl featuredImage{ url } collections{ edges{ node{ id title } } }", 1)


def eligibility(prod_lines, order_lines, today):
    """Per day: sales value of ELIGIBLE products (e) and of all order lines (t), Melbourne days.

    Same rule as the Procurement report's Introduced vs cleared (tools/procurement.py flow_aggregate): a product is eligible
    when days on market / units sold < 50 (clock stops at the last sale once sold out or discontinued), or it was published
    in the last 30 days (still being tested). No sales = not eligible. Each product keeps today's status across all history.
    Lines with no matching product (custom / POS / deleted) count as not eligible."""
    import procurement as pr
    import restock_plan as rp
    products, vprice = {}, {}
    for l in prod_lines:
        if "/Product/" not in l.get("id", "") or "__parentId" in l or (l.get("status") or "").upper() == "DRAFT":
            continue
        created = dt.datetime.fromisoformat(l["createdAt"].replace("Z", "+00:00"))
        meta = ((l.get("metafield") or {}).get("value") or "")
        if created < rp.MIGRATION_CUTOFF:
            pub = meta[:10] if len(meta) >= 10 and meta[4] == "-" else ""
        else:
            pub = rp.melbourne_day(l["createdAt"])
        products[l["id"]] = {"title": l.get("title") or "", "url": l.get("onlineStoreUrl") or "",
                             "img": ((l.get("featuredImage") or {}).get("url") or ""), "cols": [],
                             "active": (l.get("status") or "").upper() == "ACTIVE", "id": rp.num(l["id"]), "pub": pub, "stock": 0, "value": 0.0, "prices": [], "cmps": [], "s90": 0, "days_n": 0, "sold": 0, "last": "",
                             "disc": ((l.get("disc") or {}).get("value") or "").strip().lower() in ("yes", "true", "1")}
    for l in prod_lines:
        P = products.get(l.get("__parentId"))
        if P and "/Collection/" in l.get("id", "") and l.get("title"):
            P["cols"].append(l["title"])
    for l in prod_lines:
        P = products.get(l.get("__parentId"))
        if P and "/ProductVariant/" in l.get("id", ""):
            q = max(0, int(l.get("inventoryQuantity") or 0))
            P["stock"] += q
            P["value"] += q * float(l.get("price") or 0)
            vprice[rp.num(l["id"])] = float(l.get("price") or 0)
            if float(l.get("price") or 0) > 0:
                P["prices"].append(float(l["price"]))
                P["cmps"].append(float(l.get("compareAtPrice") or 0))
    cancelled = {l["id"] for l in order_lines if "/Order/" in l.get("id", "") and l.get("cancelledAt")}
    placed = {l["id"]: rp.melbourne_day(l["processedAt"]) for l in order_lines if "/Order/" in l.get("id", "") and l.get("processedAt")}
    by_pid = {P["id"]: P for P in products.values()}
    sales = []
    for l in order_lines:
        if "/LineItem/" not in l.get("id", "") or l.get("__parentId") in cancelled:
            continue
        day = placed.get(l.get("__parentId"), "")
        P = by_pid.get(rp.num((l.get("product") or {}).get("id")))
        q = int(l.get("quantity") or 0)
        rev = float((((l.get("discountedTotalSet") or {}).get("shopMoney")) or {}).get("amount") or 0)
        if not day:
            continue
        if P:
            P["sold"] += q
            P["last"] = max(P["last"], day)
            if day >= (today - dt.timedelta(days=90)).isoformat():
                P["s90"] += q
        sales.append((day, P, rev))
    if len(sales) < 50:
        raise RuntimeError("Too few order lines for the eligible split")
    for P in products.values():
        P["elig"], P["new"], P["du"] = False, False, None
        if P["pub"]:
            pub = dt.date.fromisoformat(P["pub"])
            end = today
            if (P["disc"] or P["stock"] <= 0) and P["last"]:
                end = min(today, dt.date.fromisoformat(P["last"]))
            days_n = max(1, (end - pub).days)
            P["days_n"] = days_n
            P["new"] = (today - pub).days < pr.FLOW_TEST_DAYS
            P["du"] = round(days_n / P["sold"], 1) if P["sold"] > 0 else None     # D.U new: days on market / units sold
            P["elig"] = P["new"] or (P["sold"] > 0 and days_n / P["sold"] < pr.FLOW_MAX_DTS)
    stock = {"e": 0.0, "n": 0.0}
    for P in products.values():
        if P["pub"]:                      # no published date = not counted (same as Procurement)
            stock["e" if P["elig"] else "n"] += P["value"]
    out = {}
    for day, P, rev in sales:
        o = out.setdefault(day, {"e": 0.0, "t": 0.0})
        o["t"] += rev
        if P and P["elig"]:
            o["e"] += rev
    names = {}
    for P in products.values():
        for c in P["cols"]:
            names[c] = names.get(c, 0) + 1
    clist = [c for c, n in sorted(names.items(), key=lambda x: (-x[1], x[0]))]
    cix = {c: i for i, c in enumerate(clist)}
    trim = lambda u: u.split("?")[0] if u else ""
    plist = {"cols": clist, "rows": [
        [P["title"], P["url"], trim(P["img"]), sorted({cix[c] for c in P["cols"]}), 1 if P["elig"] else 0, 1 if P["new"] else 0,
         P["stock"], round(P["value"]), P["sold"], P["du"], 1 if P["active"] else 0, 1 if P["pub"] else 0,
         round(sum(P["prices"]) / len(P["prices"]), 2) if P["prices"] else 0, P["s90"], P["days_n"],
         # on sale now = compare-at above price: original (compare-at) average, else 0
         round(sum(c for c, p in zip(P["cmps"], P["prices"]) if c > p) / max(1, sum(1 for c, p in zip(P["cmps"], P["prices"]) if c > p)), 2)
         if any(c > p for c, p in zip(P["cmps"], P["prices"])) else 0, P["id"]]
        for P in sorted(products.values(), key=lambda P: -P["value"])]}
    return {"days": out, "stock": {k: round(v) for k, v in stock.items()}, "plist": plist,
            "pelig": {P["id"]: P["elig"] for P in products.values() if P["pub"]}, "vprice": vprice}


def stock_history(elig):
    """Stock value at the end of each month from the daily inventory snapshots (Supabase public.inventory_snapshots, kept
    since 10 Nov 2026). Value = quantity x the variant's current price; eligible/not eligible = today's product status.
    Returns [{"d": date, "e": value, "n": value}] or [] when the history is unavailable (never blocks the report)."""
    try:
        tok = os.environ["SYNC_READ_TOKEN"]
        import restock_plan as rp
        rows = rp.sb_rpc("sync_stock_month_ends", {"p_token": tok})
    except Exception as exc:
        print("stock history skipped:", str(exc)[:200])
        return []
    by = {}
    for r in rows:
        pid, vid = int(r["product_id"]), int(r["variant_id"])
        if pid not in elig["pelig"]:
            continue
        g = "e" if elig["pelig"][pid] else "n"
        d = by.setdefault(r["snap_date"], {"d": r["snap_date"], "e": 0.0, "n": 0.0})
        d[g] += max(0, int(r["qty"])) * elig["vprice"].get(vid, 0.0)
    return [{"d": k, "e": round(v["e"]), "n": round(v["n"])} for k, v in sorted(by.items())]


def windsor(connector, acct, start, end):
    p = urllib.parse.urlencode({"api_key": os.environ["WINDSOR_API_KEY"], "date_from": start, "date_to": end,
                                "fields": "date,spend", "select_accounts": acct})
    with urllib.request.urlopen(f"https://connectors.windsor.ai/{connector}?{p}", timeout=120) as r:
        w = json.load(r)
    rows = w.get("data", w) if isinstance(w, dict) else w
    if not isinstance(rows, list):
        raise RuntimeError(f"Windsor {connector}: unexpected response")
    return rows


FALLBACK_ADS_SHARE = 232 / 384  # same fallback as order_source.py


def ads_share(end):
    """Google Ads share of 'Google Direction' store visits (30-day Ads directions vs GMB directions)."""
    try:
        s = (dt.date.fromisoformat(end) - dt.timedelta(days=30)).isoformat()
        e = (dt.date.fromisoformat(end) - dt.timedelta(days=1)).isoformat()
        def w(conn, fields, acct):
            p = urllib.parse.urlencode({"api_key": os.environ["WINDSOR_API_KEY"], "date_from": s, "date_to": e,
                                        "fields": ",".join(fields), "select_accounts": acct})
            with urllib.request.urlopen(f"https://connectors.windsor.ai/{conn}?{p}", timeout=240) as r:
                x = json.load(r)
            return x.get("data", x) if isinstance(x, dict) else x
        ads = sum(float(r.get("all_conversions_by_conversion_date") or 0)
                  for r in w("google_ads", ["date", "conversion_action_name", "all_conversions_by_conversion_date"], GOOGLE_ACCT)
                  if "direction" in str(r.get("conversion_action_name") or "").lower())
        gmb = sum(float(r.get("direction_requests") or 0)
                  for r in w("google_my_business", ["date", "direction_requests"],
                             os.environ.get("WINDSOR_GMB_ACCOUNT", "locations/17025975436640363354")))
        return ads / (ads + gmb) if ads + gmb > 0 else FALLBACK_ADS_SHARE
    except Exception:
        return FALLBACK_ADS_SHARE


def channel_split(src, share):
    """order_source -> {channel: fraction}. G = Google Ads, F = Facebook, O = organic & everything else."""
    s = (src or "").strip().lower()
    if s.startswith("fb ") or s.startswith("fb/"):
        return {"F": 1.0}
    if s.startswith("google online") or s.startswith("google ads"):
        return {"G": 1.0}
    if s.startswith("google direction"):
        return {"G": share, "O": 1 - share}
    return {"O": 1.0}


def daily(orders, google, meta, start, today, share=FALLBACK_ADS_SHARE, elig=None):
    days = {}
    d = dt.date.fromisoformat(start)
    while d <= today:
        days[d.isoformat()] = {"d": d.isoformat(), "G": [0.0, 0.0], "F": [0.0, 0.0], "O": [0.0, 0.0], "g": 0.0, "m": 0.0, "e": 0.0, "t": 0.0}
        d += dt.timedelta(days=1)
    for o in orders:
        if o.get("cancelledAt"):
            continue
        day = dt.datetime.fromisoformat(o["processedAt"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
        if day not in days:
            continue
        for t in o.get("transactions") or []:
            if t.get("status") != "SUCCESS":
                continue
            v = float(t["amountSet"]["shopMoney"]["amount"])
            sign = 1 if t.get("kind") in ("SALE", "CAPTURE") else -1 if t.get("kind") == "REFUND" else 0
            i = 1 if str(t.get("gateway", "")).lower() == "cash" else 0
            src = ((o.get("src") or {}).get("value")) if isinstance(o.get("src"), dict) else o.get("src")
            for ch, frac in channel_split(src, share).items():
                days[day][ch][i] += sign * v * frac
    for rows, key in ((google, "g"), (meta, "m")):
        for r in rows:
            if r.get("date") in days:
                days[r["date"]][key] += float(r.get("spend") or 0)
    for day, v in ((elig or {}).get("days") or {}).items():
        if day in days:
            days[day]["e"], days[day]["t"] = round(v["e"], 2), round(v["t"], 2)
    out = list(days.values())
    for r in out:
        for k in ("g", "m"):
            r[k] = round(r[k], 2)
        for k in ("G", "F", "O"):
            r[k] = [round(r[k][0], 2), round(r[k][1], 2)]
    return out


def build_page(rows, now, share=FALLBACK_ADS_SHARE, stock=None, flow=None, hist=None, plist=None):
    h = open(TEMPLATE, encoding="utf-8").read()
    updated = now.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    data = json.dumps({"rows": rows, "cfg": dict(CONFIG, ads_share=round(share, 4), stock=stock or {}), "flow": flow, "hist": hist or [],
                       "plist": plist}, separators=(",", ":")).replace("</", "<\\/")
    h = h.replace("__TODAY__", now.date().isoformat()).replace("__UPDATED__", updated)
    assert h.count("__DATA__") == 1
    h = h.replace("__DATA__", data)
    t = now.date()
    sales = lambda a: round(sum(sum(r[k][0] + r[k][1] for k in "GFO") for r in rows if r["d"] >= a.isoformat()), 0)
    meta = {"updated": updated, "stats": [
        [f"${sales(t):,.0f}", "sales today"],
        [f"${sales(t - dt.timedelta(days=t.weekday())):,.0f}", "sales this week"],
        [f"${sales(t.replace(day=1)):,.0f}", "sales this month"]]}
    return h, meta


def build():
    import product_visibility as pv
    now = dt.datetime.now(TZ)
    start = START
    end = now.date().isoformat()
    share = ads_share(end)
    import procurement as pr
    import restock_plan as rp
    prod_lines, order_lines = rp.bulk(product_query(), "flow products"), rp.bulk(pr.ORDERS, "orders")
    elig = eligibility(prod_lines, order_lines, now.date())
    flow = None
    try:   # the stock-flow section must never take the rest of the report down
        flow = pr.flow_aggregate(prod_lines, order_lines, now.date())
    except Exception as exc:
        print("stock flow skipped:", str(exc)[:300])
    rows = daily(fetch_orders(start), windsor("google_ads", GOOGLE_ACCT, start, end),
                 windsor("facebook", META_ACCT, start, end), start, now.date(), share, elig)
    if not any(sum(r[k][0] + r[k][1] for k in "GFO") for r in rows):
        raise RuntimeError("no sales returned")
    page, meta = build_page(rows, now, share, elig["stock"], flow, stock_history(elig), elig["plist"])
    key = os.environ["PROFIT_FLOW_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"days": len(rows), "stats": meta["stats"]}))


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        f = json.load(open(sys.argv[sys.argv.index("--fixture") + 1]))
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
        now = dt.datetime.now(TZ)
        if "--now" in sys.argv:
            now = dt.datetime.fromisoformat(sys.argv[sys.argv.index("--now") + 1]).astimezone(TZ)
        start = now.date().replace(day=1).isoformat()
        share = f.get("ads_share", FALLBACK_ADS_SHARE)
        rows = daily(f["orders"], f["google"], f["meta"], start, now.date(), share, f.get("elig"))
        page, meta = build_page(rows, now, share, (f.get("elig") or {}).get("stock"), f.get("flow"), f.get("hist"), (f.get("elig") or {}).get("plist"))
        open(os.path.join(out, "profit-flow.html"), "w", encoding="utf-8").write(page)
        json.dump(rows, open(os.path.join(out, "rows.json"), "w"))
        print(len(rows), meta)
        sys.exit(0)
    import product_visibility as pv
    pv.RID = RID
    try:
        build()
    except Exception as exc:
        try:
            pv.set_status(False, f"Profit flow build failed: {type(exc).__name__}")
        except Exception:
            pass
        raise
