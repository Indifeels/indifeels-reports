"""Reconcile Shopify custom.order_source back into the live attribution queue.

Reads the Shopify snapshot already fetched for Daily/Monthly reports and sends
only non-empty order-source values to the protected Supabase callback. This
covers attribution edits made directly in Shopify, which bypass the dashboard
callback flow.
"""
import glob
import json
import os
import sys
import urllib.request

DATA_DIR = sys.argv[1]
TOKEN = os.environ["SYNC_READ_TOKEN"]
URL = os.environ.get(
    "ORDER_ATTRIBUTION_CALLBACK",
    "https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/order-attribution-callback",
)

updates = {}
for path in sorted(glob.glob(os.path.join(DATA_DIR, "shopify*.json"))):
    x = json.load(open(path))
    if isinstance(x, dict) and "result" in x:
        x = x["result"]
    if isinstance(x, list) and x and isinstance(x[0], dict) and "text" in x[0]:
        x = json.loads(x[0]["text"])
    data = x.get("data", {}) if isinstance(x, dict) else {}
    for conn in data.values():
        for n in (conn or {}).get("nodes", []):
            oid = str(n.get("id") or "")
            mf = n.get("m") or {}
            source = str(mf.get("value") or "").strip()
            if oid.startswith("gid://shopify/Order/") and source:
                updates[oid] = source

if not updates:
    print("attribution reconciliation: no Shopify source values found")
    raise SystemExit(0)

items = [{"order_id": oid, "source": source} for oid, source in updates.items()]
changed = 0
for i in range(0, len(items), 400):
    body = json.dumps({
        "mode": "reconcile",
        "token": TOKEN,
        "updates": items[i:i + 400],
    }).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    if not out.get("ok"):
        raise RuntimeError("Attribution reconciliation failed")
    changed += int(out.get("updated") or 0)

print(f"attribution reconciliation: {changed} queue rows updated from Shopify")
