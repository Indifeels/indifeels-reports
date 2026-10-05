"""Fetch live Google Ads tracked-campaign data from Windsor.ai.

Uses the normal Windsor connector read (no forced/hourly refresh) because the
current Windsor plan supports daily/cached reads but not forced hourly pulls.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT = sys.argv[1]
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

tz = ZoneInfo("Australia/Sydney")
if os.environ.get("REPORT_NOW"):
    report_now = datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(tz)
    end = report_now.date().isoformat()
else:
    end = (datetime.now(tz).date() - timedelta(days=1)).isoformat()

start = os.environ.get("GOOGLE_TRACKED_START", "2026-07-01")
acct = os.environ.get("WINDSOR_GOOGLE_ACCOUNT", "788-887-6041")
fields = ",".join([
    "date",
    "campaign",
    "campaign_id",
    "campaign_status",
    "spend",
    "impressions",
    "clicks",
    "conversions",
    "conversions_value",
    "search_impression_share",
    "search_budget_lost_impression_share",
    "search_rank_lost_impression_share",
])

params = urllib.parse.urlencode({
    "api_key": os.environ["WINDSOR_API_KEY"],
    "date_from": start,
    "date_to": end,
    "fields": fields,
    "select_accounts": acct,
})
url = "https://connectors.windsor.ai/google_ads?" + params

with urllib.request.urlopen(url, timeout=180) as r:
    data = json.load(r)

rows = data.get("data", data) if isinstance(data, dict) else data
if not isinstance(rows, list) or not rows:
    raise RuntimeError("Windsor returned no Google Ads rows")

rows = [
    x for x in rows
    if str(x.get("campaign") or "").lower().startswith("tracked_")
]
if not rows:
    raise RuntimeError("Windsor returned no tracked Google Ads campaign rows")

json.dump({"data": rows, "date_from": start, "date_to": end}, open(OUT, "w"))
print("Google tracked inputs ready through", end, ":", len(rows), "rows")
