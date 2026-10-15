"""Build the encrypted Cash Report for the Indifeels dashboard.

Cash-paid Shopify orders since 18 Apr 2026 (cash gateway, successful SALE minus successful cash REFUND
transactions, cancelled orders excluded), one row per order dated in Melbourne time. The page template
(tools/cash_report_template.html) groups them by month > week > day > order and rounds to the nearest $5.
Tiles are relative to "today", so the Today tile resets at midnight when the schedule rebuilds it.

Runs from the Schedule Panel: after every new order and daily at 12:00 am.

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, CASH_REPORT_KEY (loaded from Supabase by the workflow)
Writes: r/cash-report.bin, r/cash-report.meta.bin, r/status.json
Offline test: python3 tools/cash_report.py --fixture orders.json --out DIR  (no Shopify, no key, no status)
"""
import datetime as dt
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv  # reuse gql, write_encrypted, set_status

RID = "cash-report"
TZ = ZoneInfo("Australia/Melbourne")
START = "2026-04-18"
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cash_report_template.html")

QUERY = """
query Cash($after:String,$q:String!){
  orders(first:50,after:$after,query:$q,sortKey:PROCESSED_AT){
    pageInfo{hasNextPage endCursor}
    nodes{
      name processedAt cancelledAt
      transactions(first:20){gateway kind status amountSet{shopMoney{amount}}}
    }
  }
}
"""


def fetch_orders():
    # Shopify dates in the search are UTC; start one day early and filter by Melbourne date below.
    q = f"gateway:cash processed_at:>={(dt.date.fromisoformat(START) - dt.timedelta(days=1)).isoformat()}"
    after, out = None, []
    while True:
        data = pv.gql(QUERY, {"after": after, "q": q})["data"]["orders"]
        out.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            return out
        after = data["pageInfo"]["endCursor"]


def cash_rows(orders, now):
    rows = []
    for o in orders:
        if o.get("cancelledAt"):
            continue
        day = dt.datetime.fromisoformat(o["processedAt"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
        if day < START or day > now.date().isoformat():
            continue
        amt = 0.0
        for t in o.get("transactions") or []:
            if str(t.get("gateway", "")).lower() != "cash" or t.get("status") != "SUCCESS":
                continue
            v = float(t["amountSet"]["shopMoney"]["amount"])
            if t.get("kind") in ("SALE", "CAPTURE"):
                amt += v
            elif t.get("kind") == "REFUND":
                amt -= v
        amt = round(amt, 2)
        if amt > 0:
            rows.append({"o": o["name"], "d": day, "c": amt, "_t": o["processedAt"]})
    rows.sort(key=lambda r: (r["d"], r["_t"]))
    for r in rows:
        del r["_t"]
    return rows


def r5(n):  # nearest $5, exact halves round down (same rule as the page)
    return (math.ceil(n / 5 - 0.5) * 5) or 0


def money(n):
    return f"${r5(n):,}"


def build_page(rows, now):
    h = open(TEMPLATE, encoding="utf-8").read()
    updated = now.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
    h = (h.replace("__ROWS__", json.dumps(rows, separators=(",", ":")))
          .replace("__TODAY__", now.date().isoformat())
          .replace("__UPDATED__", updated)
          .replace("__MONTHNAME__", now.strftime("%B")))
    assert "__" not in h.replace("__proto__", ""), "unfilled template placeholder"
    today = now.date()
    def win(a, b):
        return round(sum(r["c"] for r in rows if a.isoformat() <= r["d"] <= b.isoformat()), 2)
    meta = {"updated": updated, "stats": [
        [money(win(today.replace(day=1), today)), "cash month to date"],
        [money(win(today, today)), "cash today"],
        [money(win(today - dt.timedelta(days=6), today)), "cash last 7 days"],
    ]}
    return h, meta


def build():
    now = dt.datetime.now(TZ)
    rows = cash_rows(fetch_orders(), now)
    if not rows:
        raise RuntimeError("no cash orders returned")
    page, meta = build_page(rows, now)
    key = os.environ["CASH_REPORT_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"orders": len(rows), "latest": rows[-1]["o"], "stats": meta["stats"]}))


if __name__ == "__main__":
    pv.RID = RID
    if "--fixture" in sys.argv:
        orders = json.load(open(sys.argv[sys.argv.index("--fixture") + 1]))
        out = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
        now = dt.datetime.now(TZ)
        if "--now" in sys.argv:
            now = dt.datetime.fromisoformat(sys.argv[sys.argv.index("--now") + 1]).astimezone(TZ)
        rows = cash_rows(orders, now)
        page, meta = build_page(rows, now)
        open(os.path.join(out, "cash-report.html"), "w", encoding="utf-8").write(page)
        json.dump(rows, open(os.path.join(out, "rows.json"), "w"))
        print(len(rows), meta)
        sys.exit(0)
    try:
        build()
    except Exception as exc:
        try:
            pv.set_status(False, f"Cash report build failed: {type(exc).__name__}")
        except Exception:
            pass
        raise
