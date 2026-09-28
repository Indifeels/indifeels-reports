"""Encrypts report pages and tile summaries for the Indifeels Reports app.
Usage: python3 encrypt.py KEYS_JSON SUMMARY_DIR HUB_DIR OUT_DIR
KEYS_JSON : JSON object {"daily": "<key>", "monthly": "<key>", "stock": "<key>"} (base64) (or a path to a file containing it)
Writes OUT_DIR/<id>.bin (gzipped report HTML) and OUT_DIR/<id>.meta.bin (tile summary JSON), each = 12-byte IV + AES-256-GCM ciphertext.
"""
import base64, gzip, json, os, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

keys_arg, SUM, HUB, OUT = sys.argv[1:5]
KEYS = json.load(open(keys_arg)) if os.path.exists(keys_arg) else json.loads(keys_arg)
os.makedirs(OUT, exist_ok=True)

def money(v, dp=0):
    if v is None: return "—"
    return ("−" if v < 0 else "") + f"${abs(v):,.{dp}f}"

def enc(rid, data: bytes, suffix):
    key = base64.b64decode(KEYS[rid]); iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, gzip.compress(data, 9), None)
    open(os.path.join(OUT, f"{rid}{suffix}"), "wb").write(iv + ct)

def load(n):
    p = os.path.join(SUM, n + ".json")
    return json.load(open(p)) if os.path.exists(p) else None

SIG = {"up": "up", "hold": "hold", "down": "down", "scale": "up", "cut": "down"}
metas = {}
d = load("daily")
if d:
    metas["daily"] = dict(updated=d["updated"], stats=[[money(d["t_s"], 2), "spent today"], [str(int(d["t_m"])), "messages today"],
                     [money(d["m_sales"]), "FB sales this month"], [f'{d["m_roas"]:.2f}x' if d["m_roas"] else "—", "ROAS this month"]],
                     signal=dict(code=SIG.get(d["sig"], "hold"), label=d["sig_label"], reason=d["reason"]),
                     warn=f'{d["unatt"]} orders need a source' if d.get("unatt") else "")
m = load("monthly")
if m:
    metas["monthly"] = dict(updated=m["updated"], stats=[[money(m["np"]), f'net profit, {m["month"]}'], [f'{m["roas"]:.2f}x', "ROAS this month"],
                       [money(m["spend"]), "spend this month"], [money(m["total_np"]), f'net profit since {m["since"]}']],
                       signal=dict(code=SIG.get(m["sig"], "hold"), label=m["sig_label"], reason=m["reason"]))

k = load("stock")
if k:
    metas["stock"] = dict(updated=k["updated"], stats=[[str(k["variants"]), "variants to move"], [str(k["units"]), "units at Backup"],
                     [str(k["products"]), "products"]],
                     warn=f'{k["variants"]} variants out of stock at Shop location' if k["variants"] else "")

done = []
for rid in KEYS:
    page = os.path.join(HUB, f"{rid}.html")
    if os.path.exists(page):
        enc(rid, open(page, "rb").read(), ".bin"); done.append(rid)
    if rid in metas:
        enc(rid, json.dumps(metas[rid]).encode(), ".meta.bin")
print("encrypted:", ", ".join(done))
