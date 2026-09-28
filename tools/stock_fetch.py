"""Fetches Shopify stock and rebuilds the encrypted Shop restock report (used by the GitHub Action).
Env: SHOPIFY_TOKEN (Admin API access token), SHOPIFY_SHOP (e.g. bvdxj3-r8.myshopify.com), STOCK_KEY (base64 AES key).
Usage: python3 tools/stock_fetch.py
Writes r/stock.bin, r/stock.meta.bin and updates r/status.json (ok or fail with a short reason).
"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "tools")
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
BACKUP, SHOPLOC = "gid://shopify/Location/99841048933", "gid://shopify/Location/99623436645"
LEVELS = """query($after:String){ location(id:"%s"){ inventoryLevels(first:250, after:$after){ pageInfo{hasNextPage endCursor}
 nodes{ q: quantities(names:["available"]){quantity} item{ id s: inventoryLevel(locationId:"%s"){ q: quantities(names:["available"]){quantity} } } } } } }""" % (BACKUP, SHOPLOC)
ITEMS = """query($ids:[ID!]!){ nodes(ids:$ids){ ... on InventoryItem { id sku variant { title image { url }
 product { title status featuredMedia { preview { image { url } } } } } } } }"""


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(5):
        req = urllib.request.Request(API, body, {"Content-Type": "application/json", "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"]})
        try:
            out = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4: time.sleep(2 * (attempt + 1)); continue
            raise RuntimeError(f"Shopify API returned HTTP {e.code}")
        if out.get("errors"):
            if any("THROTTLED" in json.dumps(x) for x in out["errors"]) and attempt < 4: time.sleep(3 * (attempt + 1)); continue
            raise RuntimeError("Shopify query error: " + json.dumps(out["errors"])[:150])
        return out
    raise RuntimeError("Shopify API kept throttling")


def status(ok, reason=""):
    subprocess.run([sys.executable, os.path.join(T, "status.py"), os.path.join(ROOT, "r"), "stock", "ok" if ok else "fail", reason], check=True)


def main():
    d = tempfile.mkdtemp(); data, hub, summ = (os.path.join(d, x) for x in ("data", "hub", "sum"))
    for p in (data, hub, summ): os.makedirs(p)
    after, n = None, 0
    while True:
        n += 1
        page = gql(LEVELS, {"after": after})
        json.dump(page, open(os.path.join(data, f"stock_levels_{n:02d}.json"), "w"))
        pi = page["data"]["location"]["inventoryLevels"]["pageInfo"]
        if not pi["hasNextPage"]: break
        after = pi["endCursor"]
    ids = json.loads(subprocess.check_output([sys.executable, os.path.join(T, "stock.py"), "ids", data]))
    for i in range(0, len(ids), 100):
        json.dump(gql(ITEMS, {"ids": ids[i:i + 100]}), open(os.path.join(data, f"stock_items_{i // 100 + 1}.json"), "w"))
    env = dict(os.environ, SUMMARY_DIR=summ)
    print(subprocess.check_output([sys.executable, os.path.join(T, "stock.py"), "build", data, os.path.join(hub, "stock.html")], env=env, text=True).strip())
    subprocess.run([sys.executable, os.path.join(T, "encrypt.py"), json.dumps({"stock": os.environ["STOCK_KEY"]}), summ, hub, os.path.join(ROOT, "r")], check=True)
    print(f"pages: {n}, matches: {len(ids)}")


if __name__ == "__main__":
    try:
        main(); status(True)
    except Exception as e:
        status(False, f"Order-triggered stock refresh failed: {e}. Fix: check the SHOPIFY_TOKEN secret and the Actions log.")
        print("FAILED:", e); sys.exit(1)
