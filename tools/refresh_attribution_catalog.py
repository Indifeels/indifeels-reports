"""Refresh searchable Facebook/Google campaign attribution choices in Supabase.

The GitHub workflow owns the Windsor API key. This script fetches recent
campaign/ad-set (Meta) and campaign/ad-group (Google) metadata, deduplicates
the latest state, then sends the catalogue to the protected Supabase callback.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

KEY = os.environ["WINDSOR_API_KEY"]
TOKEN = os.environ["SYNC_READ_TOKEN"]
CALLBACK = os.environ.get(
    "ORDER_ATTRIBUTION_CALLBACK",
    "https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/order-attribution-callback",
)
DATE_TO = date.today().isoformat()
DATE_FROM = (date.today() - timedelta(days=120)).isoformat()

def fetch(connector, account, fields):
    q = urllib.parse.urlencode({
        "api_key": KEY,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "fields": ",".join(fields),
        "select_accounts": account,
    })
    with urllib.request.urlopen(
        "https://connectors.windsor.ai/" + connector + "?" + q,
        timeout=240,
    ) as r:
        x = json.load(r)
    rows = x.get("data", x) if isinstance(x, dict) else x
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Windsor returned no {connector} rows")
    return rows

def latest(rows, platform, ad_name_key, ad_id_key, ad_status_key):
    out = {}
    for r in rows:
        cid = str(r.get("campaign_id") or "").strip()
        cname = str(r.get("campaign") or "").strip()
        if not cid or not cname:
            continue
        aid = str(r.get(ad_id_key) or "").strip()
        aname = str(r.get(ad_name_key) or "").strip()
        d = str(r.get("date") or "")
        k = platform + "|" + cid + "|" + aid
        row = {
            "option_key": k,
            "platform": platform,
            "campaign_id": cid,
            "campaign_name": cname,
            "campaign_status": str(r.get("campaign_status") or "").strip() or None,
            "adset_id": aid or None,
            "adset_name": aname or None,
            "adset_status": str(r.get(ad_status_key) or "").strip() or None,
            "last_seen_date": d or None,
        }
        if k not in out or d >= str(out[k].get("last_seen_date") or ""):
            out[k] = row
    return list(out.values())

fb = fetch(
    "facebook",
    os.environ.get("WINDSOR_FACEBOOK_ACCOUNT", "1634084963432990"),
    ["date","campaign","campaign_id","campaign_status","adset_name","adset_id","adset_status"],
)
google = fetch(
    "google_ads",
    os.environ.get("WINDSOR_GOOGLE_ACCOUNT", "788-887-6041"),
    ["date","campaign","campaign_id","campaign_status","ad_group_name","ad_group_id","ad_group_status"],
)

rows = (
    latest(fb, "Facebook", "adset_name", "adset_id", "adset_status")
    + latest(google, "Google", "ad_group_name", "ad_group_id", "ad_group_status")
)
if not any(x["platform"] == "Facebook" for x in rows):
    raise RuntimeError("No Facebook attribution choices produced")
if not any(x["platform"] == "Google" for x in rows):
    raise RuntimeError("No Google attribution choices produced")

body = json.dumps({"mode":"catalog","token":TOKEN,"rows":rows}).encode()
req = urllib.request.Request(
    CALLBACK,
    data=body,
    headers={"Content-Type":"application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=180) as r:
    result = json.load(r)
if not result.get("ok"):
    raise RuntimeError("Catalogue publish failed")

print(
    "Attribution catalogue refreshed:",
    sum(1 for x in rows if x["platform"] == "Facebook"), "Facebook rows,",
    sum(1 for x in rows if x["platform"] == "Google"), "Google rows",
)
