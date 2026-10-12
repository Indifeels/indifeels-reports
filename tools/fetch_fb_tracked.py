"""Fetch read-only inputs for the Facebook TRACKED campaigns report (Windsor.ai, Meta account via Webirox).
Usage: python3 fetch_fb_tracked.py OUT_DIR
Writes OUT_DIR/windsor_01.json with only campaigns that have "Tracked" in the name (never "Non Tracked").
No write actions are performed.
"""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
tz = ZoneInfo("Australia/Sydney")
if os.environ.get("REPORT_NOW"):
    end = datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(tz).date().isoformat()
else:
    end = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
start = os.environ.get("REPORT_START", "2026-03-01")
acct = os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990")
fields = ("date,campaign,campaign_id,campaign_status,campaign_start_time,spend,impressions,clicks,link_clicks,reach,"
          "actions_purchase,action_values_purchase,actions_add_to_cart,actions_initiate_checkout,actions_landing_page_view")
params = urllib.parse.urlencode({"api_key": os.environ["WINDSOR_API_KEY"], "date_from": start, "date_to": end, "fields": fields, "select_accounts": acct})
with urllib.request.urlopen("https://connectors.windsor.ai/facebook?" + params, timeout=180) as r:
    w = json.load(r)
rows = w.get("data", w) if isinstance(w, dict) else w
if not isinstance(rows, list) or not rows:
    raise RuntimeError("Windsor returned no Meta rows")
def tracked(n):
    n = (n or "").lower().replace("-", " ")
    return "tracked" in n and "non tracked" not in n
rows = [r for r in rows if tracked(r.get("campaign"))]
if not rows:
    raise RuntimeError("Windsor returned no Tracked Meta rows")
json.dump({"data": rows}, open(os.path.join(OUT, "windsor_01.json"), "w"))
print("inputs ready through", end, ":", len(rows), "tracked Meta rows")
