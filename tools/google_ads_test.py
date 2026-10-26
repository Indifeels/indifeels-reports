"""Build the encrypted Google Ads Test report (wedding PMax guided setup and daily KPI view).

Static page for now: tools/google_ads_test_template.html is wrapped, gzipped and AES-256-GCM encrypted.
Live KPIs get added later by a Claude scheduled task (see tools/google_ads_test_REFRESH.md).

Usage:
  python3 tools/google_ads_test.py --html OUT.html     # plain preview, no key
  GOOGLE_ADS_TEST_KEY=... python3 tools/google_ads_test.py   # writes r/google-ads-test.bin, .meta.bin, status
"""
import argparse, base64, datetime as dt, gzip, json, os, subprocess, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS, RDIR, RID = os.path.join(ROOT, "tools"), os.path.join(ROOT, "r"), "google-ads-test"
ap = argparse.ArgumentParser(); ap.add_argument("--html"); args = ap.parse_args()

tpl = open(os.path.join(TOOLS, "google_ads_test_template.html"), encoding="utf-8").read()
PRE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body{margin:0}</style>')
page = PRE + tpl + "</html>"
if args.html:
    open(args.html, "w", encoding="utf-8").write(page); print("wrote", args.html); sys.exit(0)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
key = base64.b64decode(os.environ.get("GOOGLE_ADS_TEST_KEY", ""))
if len(key) != 32:
    sys.exit("GOOGLE_ADS_TEST_KEY is missing or not a 32-byte AES key")

def enc(payload):
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, gzip.compress(payload, 9), None)

now = dt.datetime.now(ZoneInfo("Australia/Melbourne"))
meta = dict(updated=now.strftime("%d %b %Y, %H:%M"),
            stats=[["—", "ROAS, wedding PMax"], ["Step 1 of 7", "setup progress"], ["—", "spend"], ["—", "purchases"]],
            signal=dict(code="hold", label="NOT LAUNCHED", reason="Wedding PMax setup is in progress."))
os.makedirs(RDIR, exist_ok=True)
open(os.path.join(RDIR, f"{RID}.bin"), "wb").write(enc(page.encode("utf-8")))
open(os.path.join(RDIR, f"{RID}.meta.bin"), "wb").write(enc(json.dumps(meta).encode("utf-8")))
subprocess.run([sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok"], check=True)
print("wrote r/google-ads-test.bin, r/google-ads-test.meta.bin")
