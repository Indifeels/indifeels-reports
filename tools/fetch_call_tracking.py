"""Fetch the raw inputs for the Call Tracking report (data only, no calculation).

Usage: fetch_call_tracking.py OUT.json

Runs three steps. Every failure is recorded (sync log in Supabase + fetch_status in OUT.json, shown on the report);
nothing is silently swallowed, but only step 3 is required for the report to publish:

  1. Google Business Profile (via Windsor): call clicks, direction requests, website clicks, impressions per day and
     location -> Supabase gmb_daily. Google reports the latest 3-5 days late, so a 45-day window is re-pulled every run;
     days Google has not published stay "Missing" (NULL), never 0.
  2. Nimbata API reconciliation -> Supabase Edge Function nimbata-sync (idempotent UPSERT on the Nimbata call id).
       REPORT_MODE=final    previous Melbourne calendar day + NIMBATA_RECHECK_DAYS earlier days (6 AM run)
       REPORT_MODE=partial  today so far (8 PM run)
     If NIMBATA_API_TOKEN is not set in Supabase this is reported as "not configured", not as an outage.
  3. Read the stable dashboard contract (sync_get_call_tracking RPC) and write OUT.json.

Env: WINDSOR_API_KEY, SYNC_READ_TOKEN (existing secrets), optional REPORT_MODE, REPORT_NOW.
No secrets are written to the output or the log.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OUT = sys.argv[1]
os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)

TZ = ZoneInfo("Australia/Melbourne")
now = datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ) if os.environ.get("REPORT_NOW") else datetime.now(TZ)
today = now.date()
mode = os.environ.get("REPORT_MODE") or ("final" if now.hour < 12 else "partial")

cfg = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.js"), encoding="utf-8").read()
SB_URL = re.search(r'url:\s*"([^"]+)"', cfg).group(1)
SB_KEY = re.search(r'key:\s*"([^"]+)"', cfg).group(1)
SYNC = os.environ["SYNC_READ_TOKEN"]
WINDSOR = os.environ["WINDSOR_API_KEY"]
status = {}


def scrub(s):
    for secret in (SYNC, WINDSOR):
        if secret:
            s = s.replace(secret, "***")
    return s[:200]


def sb_rpc(fn, body):
    req = urllib.request.Request(SB_URL + "/rest/v1/rpc/" + fn, json.dumps(body).encode(),
                                 {"apikey": SB_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read()
    except urllib.error.HTTPError as e:   # keep the database's own error message (no secrets in it) so failures are diagnosable
        raise RuntimeError("%s HTTP %d: %s" % (fn, e.code, scrub(e.read().decode("utf-8", "replace"))))
    return json.loads(t) if t else None


def log_run(integration, run_type, st, category, detail):
    try:
        sb_rpc("sync_log_run", {"p_token": SYNC, "p_integration": integration, "p_run_type": run_type,
                                "p_status": st, "p_category": category, "p_detail": detail[:300]})
    except Exception:
        pass  # the original failure is already in fetch_status; never mask it


def windsor_gmb(d_from, d_to):
    p = urllib.parse.urlencode({
        "api_key": WINDSOR, "date_from": d_from, "date_to": d_to,
        "fields": "date,location_id,location_title,call_clicks,direction_requests,website_clicks,impressions",
    })
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen("https://connectors.windsor.ai/google_my_business?" + p, timeout=240) as r:
                x = json.load(r)
            rows = x.get("data", x) if isinstance(x, dict) else x
            if not isinstance(rows, list):
                raise RuntimeError("unexpected Windsor response shape")
            return rows
        except urllib.error.HTTPError as e:
            last = ("rate_limit" if e.code == 429 else "auth" if e.code in (401, 403) else "api_failure", "HTTP %d" % e.code)
        except Exception as e:
            last = ("network", type(e).__name__ + ": " + scrub(str(e)))
        time.sleep(4 * (attempt + 1))
    raise RuntimeError("%s|%s" % last)


# ---- 1) Google Business Profile -> Supabase
g_from, g_to = (today - timedelta(days=45)).isoformat(), today.isoformat()
try:
    rows = windsor_gmb(g_from, g_to)
    if not rows:
        raise RuntimeError("api_failure|Windsor returned no Google Business Profile rows")
    res = sb_rpc("sync_put_gmb_daily", {"p_token": SYNC, "p_rows": rows, "p_from": g_from, "p_to": g_to})
    status["gmb"] = {"ok": True, "rows": len(rows), "upserted": (res or {}).get("upserted")}
except Exception as e:
    cat, _, msg = str(e).partition("|")
    if not msg:
        cat, msg = "db_failure", scrub(str(e))
    status["gmb"] = {"ok": False, "category": cat, "error": scrub(msg)}
    log_run("gmb", "gmb_sync", "error", cat, msg)

# ---- 2) Nimbata API reconciliation -> Edge Function
try:
    req = urllib.request.Request(SB_URL + "/functions/v1/nimbata-sync", json.dumps({"mode": mode}).encode(),
                                 {"Content-Type": "application/json", "x-sync-token": SYNC})
    try:
        with urllib.request.urlopen(req, timeout=170) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        body.setdefault("ok", False)
    if body.get("configured") is False:
        status["nimbata"] = {"ok": True, "configured": False, "note": "NIMBATA_API_TOKEN not set; webhook data only"}
    elif body.get("ok"):
        status["nimbata"] = {"ok": True, "configured": True, "mode": mode, "calls": body.get("calls"),
                             "inserted": body.get("inserted"), "updated": body.get("updated")}
    else:
        status["nimbata"] = {"ok": False, "category": body.get("category", "api_failure"), "error": scrub(str(body.get("error", "")))}
except Exception as e:
    status["nimbata"] = {"ok": False, "category": "network", "error": scrub(str(e))}
    log_run("nimbata", "api_reconciliation", "error", "network", str(e))

# ---- 3) stable dashboard contract (required)
try:
    data = sb_rpc("sync_get_call_tracking", {"p_token": SYNC, "p_days": 60})
    if not isinstance(data, dict) or "summary" not in data:
        raise RuntimeError("unexpected contract shape")
except Exception as e:
    raise SystemExit("Required source failed: call tracking contract: " + scrub(str(e)))
status["contract"] = {"ok": True}

json.dump({"now": now.isoformat(), "mode": mode, "fetch_status": status, "data": data}, open(OUT, "w"))
print("Call tracking inputs ready (%s): GMB %s | Nimbata %s | %d calls, %d gmb rows" % (
    mode, "ok" if status["gmb"].get("ok") else "FAILED", "ok" if status["nimbata"].get("ok") else "FAILED",
    len(data.get("calls", [])), len(data.get("gmb_daily", []))))
