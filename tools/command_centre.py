"""Build the encrypted Master Dashboard (Command Centre): scored business areas, alerts, drill-down tiles and connections map.

Static page for now (sample scores and alerts): tools/command_centre_template.html is wrapped, gzipped and AES-256-GCM encrypted.
Real scores and alerts get wired in later from each report.

Usage:
  python3 tools/command_centre.py --html OUT.html     # plain preview, no key
  COMMAND_CENTRE_KEY=... python3 tools/command_centre.py   # writes r/command-centre.bin, .meta.bin, status
"""
import argparse, base64, datetime as dt, gzip, json, os, subprocess, sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS, RDIR, RID = os.path.join(ROOT, "tools"), os.path.join(ROOT, "r"), "command-centre"
ap = argparse.ArgumentParser(); ap.add_argument("--html"); args = ap.parse_args()

tpl = open(os.path.join(TOOLS, "command_centre_template.html"), encoding="utf-8").read()
PRE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body{margin:0}</style>')
page = PRE + tpl + "</html>"
if args.html:
    open(args.html, "w", encoding="utf-8").write(page); print("wrote", args.html); sys.exit(0)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
key = base64.b64decode(os.environ.get("COMMAND_CENTRE_KEY", ""))
if len(key) != 32:
    sys.exit("COMMAND_CENTRE_KEY is missing or not a 32-byte AES key")

def enc(payload):
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, gzip.compress(payload, 9), None)

now = dt.datetime.now(ZoneInfo("Australia/Melbourne"))
meta = dict(updated=now.strftime("%d %b %Y, %H:%M"),
            stats=[["63", "overall score (sample)"], ["9", "areas"], ["23", "built tiles"], ["70+", "planned tiles"]],
            signal=dict(code="hold", label="DRAFT", reason="Sample scores and alerts until each report feeds its own."))
os.makedirs(RDIR, exist_ok=True)
open(os.path.join(RDIR, f"{RID}.bin"), "wb").write(enc(page.encode("utf-8")))
open(os.path.join(RDIR, f"{RID}.meta.bin"), "wb").write(enc(json.dumps(meta).encode("utf-8")))
subprocess.run([sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok"], check=True)
print("wrote r/command-centre.bin, r/command-centre.meta.bin")
