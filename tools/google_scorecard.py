"""Build the encrypted Google Tracked Scorecard (hub report id: google-scorecard).

A charcoal-tile scorecard for the Google Ads marketer: KPI tiles scored out of 100 (sortable by priority or by
process step), period tiles, daily profit chart, order-attribution grid (Google / Facebook / Organic from the
Shopify `custom.order_source` field, with links to each order in Shopify admin), and campaign, ad group, keyword and
search-term drill-downs. Template: tools/google_scorecard_template.html (all logic runs in the page).

The numbers come from a JSON file of raw inputs that a Claude scheduled task collects from Windsor.ai (Google Ads,
GA4, Search Console, Google Business Profile) and Shopify. The inputs are NOT stored in this public repo; only the
encrypted output is. See tools/google_scorecard_REFRESH.md for the input schema and refresh steps.

Usage:
  python3 tools/google_scorecard.py DATA.json                 # needs GOOGLE_SCORECARD_KEY; writes r/google-scorecard.bin, .meta.bin, status
  python3 tools/google_scorecard.py DATA.json --html OUT.html # plain preview page, no key, no status
Env: GOOGLE_SCORECARD_KEY (base64 AES-256 key, from Supabase report_keys where report_id='google-scorecard')
"""
import argparse
import base64
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
RDIR = os.path.join(ROOT, "r")
RID = "google-scorecard"
TZ = ZoneInfo("Australia/Melbourne")
NET = 0.75 / 1.1       # revenue ex GST x product margin
EXPERT_WEEK = 155.0     # Google Ads expert cost per week

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--html")
args = ap.parse_args()
D = json.load(open(args.data, encoding="utf-8"))
for k in ("orders", "ads", "camps", "life", "meta", "cstat", "ids"):
    if k not in D:
        sys.exit(f"input is missing '{k}' (see tools/google_scorecard_REFRESH.md)")

# ---- tile summary (simple 30-day numbers; the page computes the full scorecard)
days = sorted(D["life"])[-30:]
spend = sum(D["life"][d][0] for d in days)
fee = EXPERT_WEEK / 7 * len(days)
rev = 0.0
n_google = 0
window = set(days)
for o in D["orders"]:
    day = dt.datetime.fromisoformat(o["t"].replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d")
    if o.get("m") == "GW" and o["a"] > 0 and day in window:
        rev += o["a"]
        n_google += 1
profit = rev * NET - spend - fee
roas = rev / spend if spend else 0
be_roas = (spend + fee) / (spend * NET) if spend else 0

def money(v):
    return ("-" if v < 0 else "") + f"${abs(v):,.0f}"

code = "up" if profit > 0 else ("hold" if roas >= 1.5 else "down")
tile_meta = dict(
    updated=D["meta"]["refreshed"],
    stats=[[money(spend), "tracked spend, 30 days"], [money(rev), "Shopify Google revenue, 30 days"],
           [f"{roas:.2f}x", "ROAS (break-even %.1fx)" % be_roas], [money(profit), "profit after expert fee, 30 days"]],
    signal=dict(code=code, label=f"ROAS {roas:.1f}x",
                reason=f"{n_google} Google orders for {money(spend)} spend; break-even ROAS is {be_roas:.1f}x."),
    warn=D["meta"].get("warn", ""),
    spark=None,
)

tpl = open(os.path.join(TOOLS, "google_scorecard_template.html"), encoding="utf-8").read()
page = tpl.replace("/*__DATA__*/null", json.dumps(D, ensure_ascii=False).replace("</", "<\\/"))
print(f"30d spend {money(spend)} | Shopify Google rev {money(rev)} | ROAS {roas:.2f}x | profit {money(profit)}")

if args.html:
    open(args.html, "w", encoding="utf-8").write(page)
    print("wrote", args.html)
    sys.exit(0)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

key = base64.b64decode(os.environ.get("GOOGLE_SCORECARD_KEY", "").strip() or "")
if len(key) != 32:
    sys.exit("GOOGLE_SCORECARD_KEY is missing or not a 32-byte AES key")


def enc(payload):
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, gzip.compress(payload, 9), None)


os.makedirs(RDIR, exist_ok=True)
open(os.path.join(RDIR, f"{RID}.bin"), "wb").write(enc(page.encode("utf-8")))
open(os.path.join(RDIR, f"{RID}.meta.bin"), "wb").write(enc(json.dumps(tile_meta).encode("utf-8")))
subprocess.run([sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok"], check=True)
print("wrote r/google-scorecard.bin, r/google-scorecard.meta.bin")
