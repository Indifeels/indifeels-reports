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
TZ = ZoneInfo("Australia/Melbourne")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profit_flow_template.html")
GOOGLE_ACCT = os.environ.get("WINDSOR_GOOGLE_ADS_ACCOUNT", "788-887-6041")
META_ACCT = os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990")

# Edit here. Monthly AUD costs are spread evenly per day of the month. amount None = not set yet (hidden on the chart).
CONFIG = {
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


def daily(orders, google, meta, start, today, share=FALLBACK_ADS_SHARE):
    days = {}
    d = dt.date.fromisoformat(start)
    while d <= today:
        days[d.isoformat()] = {"d": d.isoformat(), "G": [0.0, 0.0], "F": [0.0, 0.0], "O": [0.0, 0.0], "g": 0.0, "m": 0.0}
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
    out = list(days.values())
    for r in out:
        for k in ("g", "m"):
            r[k] = round(r[k], 2)
        for k in ("G", "F", "O"):
            r[k] = [round(r[k][0], 2), round(r[k][1], 2)]
    return out


def build_page(rows, now, share=FALLBACK_ADS_SHARE):
    h = open(TEMPLATE, encoding="utf-8").read()
    updated = now.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    h = (h.replace("__DATA__", json.dumps({"rows": rows, "cfg": dict(CONFIG, ads_share=round(share, 4))}, separators=(",", ":")))
          .replace("__TODAY__", now.date().isoformat()).replace("__UPDATED__", updated))
    assert "__" not in h.replace("__proto__", ""), "unfilled template placeholder"
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
    start = now.date().replace(day=1).isoformat()
    end = now.date().isoformat()
    share = ads_share(end)
    rows = daily(fetch_orders(start), windsor("google_ads", GOOGLE_ACCT, start, end),
                 windsor("facebook", META_ACCT, start, end), start, now.date(), share)
    if not any(sum(r[k][0] + r[k][1] for k in "GFO") for r in rows):
        raise RuntimeError("no sales returned")
    page, meta = build_page(rows, now, share)
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
        rows = daily(f["orders"], f["google"], f["meta"], start, now.date(), share)
        page, meta = build_page(rows, now, share)
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
