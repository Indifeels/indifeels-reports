"""Fetch the raw inputs for the Google Ads Tracked report (data only, no calculation).

Writes one JSON file:
  campaigns   daily campaign rows, every Google campaign (the builder decides what is "tracked")
  adgroups / keywords / search_terms   {"lifetime": [...], "last30": [...], "last15": [...], "last7": [...]}
  orders      Shopify web orders with journey/UTM data and the order_source metafield
  fetch_status per-source ok / error text, so the builder can label missing data instead of guessing

Required sources (the job fails and the last valid report stays live): campaigns, orders.
Optional sources (ad group, keyword, search term): failures are recorded and shown as "data unavailable".
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
today = now.date()
yesterday = today - timedelta(days=1)
# Pull through today so the optional TODAY - PARTIAL block can exist; the builder keeps completed days separate.
end = today.isoformat()
start = os.environ.get("GOOGLE_TRACKED_START", "2026-01-01")
acct = os.environ.get("WINDSOR_GOOGLE_ACCOUNT", "788-887-6041")
KEY = os.environ["WINDSOR_API_KEY"]
status = {}


def windsor(fields, d_from, d_to):
    p = urllib.parse.urlencode({
        "api_key": KEY, "date_from": d_from, "date_to": d_to,
        "fields": ",".join(fields), "select_accounts": acct,
    })
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen("https://connectors.windsor.ai/google_ads?" + p, timeout=240) as r:
                x = json.load(r)
            rows = x.get("data", x) if isinstance(x, dict) else x
            if not isinstance(rows, list):
                raise RuntimeError("unexpected Windsor response shape")
            return rows
        except Exception as e:  # never include the URL (it carries the key)
            last = type(e).__name__ + ": " + str(e).replace(KEY, "***")[:160]
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(last)


out = {"date_from": start, "date_to": end, "now": now.isoformat(), "fetch_status": status}

# ---- required: campaigns by day
try:
    rows = windsor(["date", "campaign", "campaign_id", "campaign_status", "campaign_type", "budget_amount",
                    "spend", "impressions", "clicks", "conversions", "conversions_value",
                    "all_conversions", "all_conversions_value",
                    "search_impression_share", "search_budget_lost_impression_share",
                    "search_rank_lost_impression_share"], start, end)
    if not rows:
        raise RuntimeError("Windsor returned no Google Ads rows")
    out["campaigns"] = rows
    status["campaigns"] = {"ok": True, "rows": len(rows)}
except Exception as e:
    raise SystemExit("Required source failed: Google Ads campaigns: " + str(e))

# ---- optional: ad groups by day (needed for the ad-group rows and their health/rank)
try:
    ag = windsor(["date", "campaign", "campaign_id", "ad_group_name", "spend", "impressions", "clicks", "conversions", "conversions_value"], start, end)
    out["adgroups_daily"] = [r for r in ag if "tracked" in str(r.get("campaign") or "").lower()
                             and "non tracked" not in str(r.get("campaign") or "").lower().replace("-", " ")
                             and r.get("ad_group_name") and (r.get("spend") or r.get("impressions"))]
    status["adgroups_daily"] = {"ok": True, "rows": len(out["adgroups_daily"])}
except Exception as e:
    status["adgroups_daily"] = {"ok": False, "error": str(e)}

# ---- optional: Google conversions by CONVERSION date and campaign (value is matched to Shopify order subtotals)
try:
    cv = windsor(["date", "campaign", "campaign_id", "conversion_action_name", "conversions_by_conversion_date", "conversions_value_by_conversion_date"], start, end)
    out["conversions_daily"] = [r for r in cv if "tracked" in str(r.get("campaign") or "").lower()
                                and "non tracked" not in str(r.get("campaign") or "").lower().replace("-", " ")
                                and (r.get("conversions_by_conversion_date") or r.get("conversions_value_by_conversion_date"))]
    status["conversions_daily"] = {"ok": True, "rows": len(out["conversions_daily"])}
except Exception as e:
    status["conversions_daily"] = {"ok": False, "error": str(e)}

# ---- optional: drilldown (limited to tracked campaigns by the builder)
w30 = (yesterday - timedelta(days=29)).isoformat()
w7 = (yesterday - timedelta(days=6)).isoformat()
w15 = (yesterday - timedelta(days=14)).isoformat()
yend = yesterday.isoformat()
ENT = {
    "keywords": ["campaign", "campaign_id", "ad_group_name", "keyword_text", "keyword_match_type", "spend", "impressions", "clicks", "conversions", "conversions_value"],
    "search_terms": ["campaign", "campaign_id", "ad_group_name", "search_term", "spend", "impressions", "clicks", "conversions", "conversions_value"],
}
for name, flds in ENT.items():
    out[name] = {}
    for label, a in (("lifetime", start), ("last30", w30), ("last15", w15), ("last7", w7)):
        try:
            rr = windsor(flds, a, yend)
            out[name][label] = [r for r in rr if "tracked" in str(r.get("campaign") or "").lower()
                                and "non tracked" not in str(r.get("campaign") or "").lower().replace("-", " ")]
            status[name + "." + label] = {"ok": True, "rows": len(out[name][label])}
        except Exception as e:
            out[name][label] = None
            status[name + "." + label] = {"ok": False, "error": str(e)}

# ---- required: Shopify orders (journey UTM + order_source)
shop = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
api = "https://" + shop + "/admin/api/2026-04/graphql.json"
Q = '''query($after:String,$query:String!){ orders(first:100,after:$after,query:$query,sortKey:PROCESSED_AT){
 pageInfo{hasNextPage endCursor}
 nodes{ id name processedAt cancelledAt displayFinancialStatus sourceName
  m:metafield(namespace:"custom",key:"order_source"){value}
  currentSubtotalPriceSet{shopMoney{amount}} currentTotalPriceSet{shopMoney{amount}} totalPriceSet{shopMoney{amount}} totalRefundedSet{shopMoney{amount}}
  customerJourneySummary{ ready
   firstVisit{source landingPage referrerUrl utmParameters{source medium campaign term content}}
   lastVisit{source landingPage referrerUrl utmParameters{source medium campaign term content}} } } } }'''
try:
    nodes, after = [], None
    while True:
        body = json.dumps({"query": Q, "variables": {"after": after, "query": "processed_at:>=" + start}}).encode()
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
        time.sleep(.4)
    if not nodes:
        raise RuntimeError("Shopify returned no orders")
    out["orders"] = nodes
    status["orders"] = {"ok": True, "rows": len(nodes)}
except Exception as e:
    msg = str(e)
    if os.environ.get("SHOPIFY_TOKEN"):
        msg = msg.replace(os.environ["SHOPIFY_TOKEN"], "***")
    raise SystemExit("Required source failed: Shopify orders: " + msg[:200])

json.dump(out, open(OUT, "w"))
print("Google tracked inputs ready through", end, ":", len(out["campaigns"]), "campaign rows,", len(nodes), "orders;",
      "optional ok:", sum(1 for k, v in status.items() if v.get("ok")), "/", len(status))
