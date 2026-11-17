"""Build the encrypted Social Push List (admin-only): not-eligible products that only need a push (50-100 days per unit, no discount).

Reads the Profit Flow page (decrypted with PROFIT_FLOW_KEY) so the tier rule stays the same as the clearance plan.
Usage:
  PROFIT_FLOW_KEY=... SOCIAL_PUSH_KEY=... python3 tools/social_push.py
"""
import base64, datetime as dt, gzip, json, os, re, subprocess, sys
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS, RDIR, RID = os.path.join(ROOT, "tools"), os.path.join(ROOT, "r"), "social-push"
PROTECT_DAYS, SLOW_DU = 90, 100          # same tiers as the Profit Flow clearance plan
MIN_DU = 50                               # below this a product is eligible

def key(name):
    k = base64.b64decode(os.environ.get(name, ""))
    if len(k) != 32:
        sys.exit(f"{name} is missing or not a 32-byte AES key")
    return k

def dec(k, b):
    return gzip.decompress(AESGCM(k).decrypt(b[:12], b[12:], None)).decode("utf-8")

def enc(k, payload):
    iv = os.urandom(12)
    return iv + AESGCM(k).encrypt(iv, gzip.compress(payload, 9), None)

pf = dec(key("PROFIT_FLOW_KEY"), open(os.path.join(RDIR, "profit-flow.bin"), "rb").read())
D = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', pf, re.S).group(1))
rows = []
for r in D["plist"]["rows"]:
    title, url, img, _c, elig, new, stock, val, sold, du, active, pub, price, s90, days, cmp_, pid = r
    if not (active and pub) or elig or stock <= 0 or sold <= 0 or du is None or days < PROTECT_DAYS:
        continue
    if MIN_DU <= du < SLOW_DU:
        rows.append(dict(t=title, u=url, i=img, p=price, s=stock, v=val, du=du, sold=sold))
rows.sort(key=lambda x: -x["v"])
data = dict(asOf=D["flow"]["asOf"], value=sum(x["v"] for x in rows), rows=rows)
tpl = open(os.path.join(TOOLS, "social_push_template.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
PRE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body{margin:0}</style>')
page = PRE + tpl + "</html>"
if len(sys.argv) > 2 and sys.argv[1] == "--html":
    open(sys.argv[2], "w", encoding="utf-8").write(page); print("wrote", sys.argv[2], len(rows), "products"); sys.exit(0)
k = key("SOCIAL_PUSH_KEY")
now = dt.datetime.now(ZoneInfo("Australia/Melbourne"))
meta = dict(updated=now.strftime("%d %b %Y, %H:%M"),
            stats=[[str(len(rows)), "products to push"], ["${:,.0f}".format(data["value"]), "stock value"], ["0", "posted"], [data["asOf"], "data as of"]],
            signal=dict(code="hold", label="DRAFT", reason="Captions are drafts. Every post needs approval."))
os.makedirs(RDIR, exist_ok=True)
open(os.path.join(RDIR, f"{RID}.bin"), "wb").write(enc(k, page.encode("utf-8")))
open(os.path.join(RDIR, f"{RID}.meta.bin"), "wb").write(enc(k, json.dumps(meta).encode("utf-8")))
subprocess.run([sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok"], check=True)
print("wrote", RID, len(rows), "products")
