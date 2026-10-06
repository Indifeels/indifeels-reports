"""Fetch the raw inputs for the Order Source report (data only, no calculation).

Usage: fetch_order_source.py OUT.json

Writes one JSON file:
  end         last complete Melbourne day (yesterday); today is never included
  fb          Meta Ads spend by day and campaign
  google      Google Ads spend by day and campaign
  ads_dirs    Google Ads "directions" conversions by day (store visits driven by ads)
  gmb_dirs    Google Business Profile direction requests by day (store visits driven by GMB)
  orders      Shopify orders (created time, current total, custom.order_source) for the last 60 days
  fetch_status per-source ok / error text

Required sources (the job fails and the last valid report stays live): fb, google, orders.
Optional sources (ads_dirs, gmb_dirs): if missing, the builder keeps the stored 60/40 split and says so on the page.
No secrets are ever written to the output or the log.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT = sys.argv[1]
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

TZ = ZoneInfo("Australia/Melbourne")
if os.environ.get("REPORT_NOW"):
    now = datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)
else:
    now = datetime.now(TZ)
end = now.date() - timedelta(days=1)  # complete days only
start = end - timedelta(days=59)      # 30 days + the previous 30 days

KEY = os.environ["WINDSOR_API_KEY"]
FB_ACCT = os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990")
G_ACCT = os.environ.get("WINDSOR_GOOGLE_ACCOUNT", "788-887-6041")
GMB_ACCT = os.environ.get("WINDSOR_GMB_ACCOUNT", "locations/17025975436640363354")
status = {}


def windsor(connector, fields, acct, d_from, d_to):
    p = urllib.parse.urlencode({
        "api_key": KEY, "date_from": d_from, "date_to": d_to,
        "fields": ",".join(fields), "select_accounts": acct,
    })
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen("https://connectors.windsor.ai/" + connector + "?" + p, timeout=240) as r:
                x = json.load(r)
            rows = x.get("data", x) if isinstance(x, dict) else x
            if not isinstance(rows, list):
                raise RuntimeError("unexpected Windsor response shape")
            return rows
        except Exception as e:  # never include the URL (it carries the key)
            last = type(e).__name__ + ": " + str(e).replace(KEY, "***")[:160]
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


s, e = start.isoformat(), end.isoformat()
out = {"end": e, "start": s, "now": now.isoformat(), "fetch_status": status}

# ---- required: Meta Ads spend by day and campaign
try:
    rows = windsor("facebook", ["date", "campaign", "spend"], FB_ACCT, s, e)
    if not rows:
        raise RuntimeError("Windsor returned no Meta rows")
    out["fb"] = [{"date": r.get("date"), "campaign": r.get("campaign"), "spend": r.get("spend") or 0} for r in rows]
    status["fb"] = {"ok": True, "rows": len(rows)}
except Exception as ex:
    raise SystemExit("Required source failed: Meta Ads spend: " + str(ex))

# ---- required: Google Ads spend by day and campaign
try:
    rows = windsor("google_ads", ["date", "campaign", "spend"], G_ACCT, s, e)
    if not rows:
        raise RuntimeError("Windsor returned no Google Ads rows")
    out["google"] = [{"date": r.get("date"), "campaign": r.get("campaign"), "spend": r.get("spend") or 0} for r in rows]
    status["google"] = {"ok": True, "rows": len(rows)}
except Exception as ex:
    raise SystemExit("Required source failed: Google Ads spend: " + str(ex))

# ---- optional: Google Ads directions conversions (counted by conversion date)
try:
    rows = windsor("google_ads", ["date", "conversion_action_name", "all_conversions_by_conversion_date"], G_ACCT, s, e)
    out["ads_dirs"] = [{"date": r.get("date"), "n": r.get("all_conversions_by_conversion_date") or 0}
                       for r in rows if "direction" in str(r.get("conversion_action_name") or "").lower()]
    status["ads_dirs"] = {"ok": True, "rows": len(out["ads_dirs"])}
except Exception as ex:
    out["ads_dirs"] = None
    status["ads_dirs"] = {"ok": False, "error": str(ex)}

# ---- optional: Google Business Profile direction requests (the most recent days report 0 because of lag)
try:
    rows = windsor("google_my_business", ["date", "direction_requests"], GMB_ACCT, s, e)
    out["gmb_dirs"] = [{"date": r.get("date"), "n": r.get("direction_requests") or 0} for r in rows]
    status["gmb_dirs"] = {"ok": True, "rows": len(out["gmb_dirs"])}
except Exception as ex:
    out["gmb_dirs"] = None
    status["gmb_dirs"] = {"ok": False, "error": str(ex)}

# ---- required: Shopify orders with the custom.order_source metafield
shop = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
api = "https://" + shop + "/admin/api/2026-04/graphql.json"
Q = '''query($after:String,$query:String!){ orders(first:250,after:$after,query:$query,sortKey:CREATED_AT){
 pageInfo{hasNextPage endCursor}
 nodes{ name createdAt currentTotalPriceSet{shopMoney{amount}} m:metafield(namespace:"custom",key:"order_source"){value} } } }'''
try:
    nodes, after = [], None
    # Start a day early; the builder filters by Melbourne calendar date.
    q = "created_at:>=" + (start - timedelta(days=1)).isoformat()
    while True:
        body = json.dumps({"query": Q, "variables": {"after": after, "query": q}}).encode()
        req = urllib.request.Request(api, body, {"Content-Type": "application/json",
                                                 "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"]})
        with urllib.request.urlopen(req, timeout=120) as r:
            x = json.load(r)
        if x.get("errors"):
            raise RuntimeError("Shopify GraphQL error: " + json.dumps(x["errors"])[:200])
        c = x["data"]["orders"]
        nodes.extend(c["nodes"])
        if not c["pageInfo"]["hasNextPage"]:
            break
        after = c["pageInfo"]["endCursor"]
        time.sleep(.3)
    if not nodes:
        raise RuntimeError("Shopify returned no orders")
    out["orders"] = [{"name": n["name"], "created": n["createdAt"],
                      "amount": float(n["currentTotalPriceSet"]["shopMoney"]["amount"]),
                      "source": ((n.get("m") or {}).get("value") or "").strip()} for n in nodes]
    status["orders"] = {"ok": True, "rows": len(nodes)}
except Exception as ex:
    msg = str(ex)
    if os.environ.get("SHOPIFY_TOKEN"):
        msg = msg.replace(os.environ["SHOPIFY_TOKEN"], "***")
    raise SystemExit("Required source failed: Shopify orders: " + msg[:200])

json.dump(out, open(OUT, "w"))
print("Order source inputs ready through", e, ":", len(out["fb"]), "Meta rows,", len(out["google"]), "Google rows,",
      len(nodes), "orders; optional ok:", sum(1 for k in ("ads_dirs", "gmb_dirs") if status[k].get("ok")), "/ 2")
