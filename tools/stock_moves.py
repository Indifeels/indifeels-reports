"""Keeps the log of automatic Backup -> Shop location stock moves (encrypted as r/stock_moves.bin).
The app shows every move that hasn't been finalised yet as a tick box; ticks live in Supabase (stock_ticks).
File (after decryption, gzip JSON): {"updated": ISO, "moves": [move...], "now": {item_id: {"shop": n, "backup": n}}}
move = {"id", "item", "product", "variant", "sku", "img", "moved_at", "order", "shop_after", "backup_after"}

CLI (used once by hand):  python3 stock_moves.py add R_DIR KEY_B64 MOVES_JSON_FILE
"""
import base64, gzip, json, os, sys, datetime as dt
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEEP_DAYS = 90
TZ = ZoneInfo("Australia/Sydney")


def now_iso():
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def load(r_dir, key_b64):
    p = os.path.join(r_dir, "stock_moves.bin")
    if not os.path.exists(p): return {"moves": [], "now": {}}
    b = open(p, "rb").read()
    return json.loads(gzip.decompress(AESGCM(base64.b64decode(key_b64)).decrypt(b[:12], b[12:], None)))


def save(r_dir, key_b64, log):
    cut = (dt.datetime.now(TZ) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    log["moves"] = [m for m in log["moves"] if m["moved_at"] >= cut]
    keep = {m["item"] for m in log["moves"]}
    log["now"] = {k: v for k, v in log.get("now", {}).items() if k in keep}
    log["updated"] = now_iso()
    iv = os.urandom(12)
    ct = AESGCM(base64.b64decode(key_b64)).encrypt(iv, gzip.compress(json.dumps(log).encode(), 9), None)
    open(os.path.join(r_dir, "stock_moves.bin"), "wb").write(iv + ct)


def record(log, item, info, shop_after, backup_after, order=""):
    t = now_iso()
    m = dict(id=f"{item.rsplit('/', 1)[-1]}@{t}", item=item, product=info.get("product", ""), variant=info.get("variant", ""),
             sku=info.get("sku", ""), img=info.get("img", ""), moved_at=t, order=order, shop_after=shop_after, backup_after=backup_after)
    log["moves"].append(m)
    log.setdefault("now", {})[item] = {"shop": shop_after, "backup": backup_after}
    return m


def item_info(node):
    """Flatten an InventoryItem node from the nodes(ids:) query."""
    v = node.get("variant") or {}
    p = v.get("product") or {}
    img = (v.get("image") or {}).get("url") or (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url") or ""
    vt = v.get("title") or ""
    return dict(product=p.get("title") or "", variant="" if vt == "Default Title" else vt, sku=node.get("sku") or "", img=img)


if __name__ == "__main__" and sys.argv[1] == "add":
    r_dir, key, src = sys.argv[2:5]
    log = load(r_dir, key)
    for x in json.load(open(src)):
        record(log, x["item"], x, x["shop_after"], x["backup_after"], x.get("order", ""))
    save(r_dir, key, log)
    print("moves logged:", len(log["moves"]))
