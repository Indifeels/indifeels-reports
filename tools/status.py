"""Records the result of a report refresh so the app can flag failed or stale reports.
Usage: python3 status.py R_DIR REPORT_ID ok
       python3 status.py R_DIR REPORT_ID fail "what failed and what to fix"
Writes R_DIR/status.json: {report_id: {"ok": bool, "at": ISO time, "last_ok": ISO time, "reason": str}}.
Keep reasons short and plain (step name, error type). Never include keys, tokens or customer data.
"""
import json, os, sys, datetime as dt, subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def code_sha():
    if os.environ.get("REPORT_CODE_SHA"):
        return os.environ["REPORT_CODE_SHA"]
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"

def manifest_version():
    if os.environ.get("REPORT_MANIFEST_VERSION"):
        return os.environ["REPORT_MANIFEST_VERSION"]
    try:
        return str(json.loads((ROOT/"reports-manifest.json").read_text()).get("manifest_version","unknown"))
    except Exception:
        return "unknown"

R, rid, res = sys.argv[1], sys.argv[2], sys.argv[3]
reason = sys.argv[4] if len(sys.argv) > 4 else ""
p = os.path.join(R, "status.json")
st = json.load(open(p)) if os.path.exists(p) else {}
now = dt.datetime.now(ZoneInfo("Australia/Sydney")).isoformat(timespec="minutes")
cur = st.get(rid, {})
ok = res == "ok"
st[rid] = {
    "ok": ok,
    "at": now,
    "last_ok": now if ok else cur.get("last_ok"),
    "reason": "" if ok else reason[:300],
    "code_sha": code_sha(),
    "manifest_version": manifest_version(),
    "data_through": os.environ.get("REPORT_NOW") or cur.get("data_through")
}
json.dump(st, open(p, "w"), indent=1, sort_keys=True)
print(f"status {rid}: {'ok' if ok else 'FAILED'}")
