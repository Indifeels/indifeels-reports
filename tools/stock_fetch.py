"""Fetches Shopify stock, moves 1 unit Backup -> Shop location for every variant at exactly 0 in Shop location
with stock at Backup, logs each move for the app's tick list, and rebuilds the encrypted Shop restock report.
Used by the GitHub Action (after every order, and 7am / 3pm).
Env: SHOPIFY_TOKEN (Admin API token with read/write inventory), SHOPIFY_SHOP, STOCK_KEY (base64 AES key), ORDER (optional).
Writes r/stock.bin, r/stock.meta.bin, r/stock_moves.bin and updates r/status.json.
Rules agreed with the owner: move only when Shop location is exactly 0 (never when it is negative: a negative
means it sold before the team moved it, and the app flags that); move 1 unit even if Backup has only 1.
"""
import json, os, subprocess, sys, tempfile, time, uuid, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stock_moves

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "tools")
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
BACKUP, SHOPLOC = "gid://shopify/Location/99841048933", "gid://shopify/Location/99623436645"
LEVELS = """query($after:String){ location(id:"%s"){ inventoryLevels(first:250, after:$after){ pageInfo{hasNextPage endCursor}
 nodes{ q: quantities(names:["available"]){quantity} item{ id s: inventoryLevel(locationId:"%s"){ q: quantities(names:["available"]){quantity} } } } } } }""" % (BACKUP, SHOPLOC)
MOVE = """mutation($input: InventoryAdjustQuantitiesInput!, $key: String!){ inventoryAdjustQuantities(input:$input) @idempotent(key:$key){
 inventoryAdjustmentGroup{ id } userErrors{ field message code } } }"""
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
    key = os.environ["STOCK_KEY"]; r_dir = os.path.join(ROOT, "r")
    lv = {}
    for f in sorted(os.listdir(data)):
        for nd in json.load(open(os.path.join(data, f)))["data"]["location"]["inventoryLevels"]["nodes"]:
            q = lambda x: (x or [{}])[0].get("quantity") or 0
            lv[nd["item"]["id"]] = [q((nd["item"].get("s") or {}).get("q")), q(nd.get("q"))]
    # --- automatic moves: Shop location exactly 0 and Backup has stock ---
    cand = [i for i, (sh, bk) in lv.items() if sh == 0 and bk > 0]
    info = {}
    for i in range(0, len(cand), 100):
        for nd in gql(ITEMS, {"ids": cand[i:i + 100]})["data"]["nodes"]:
            if nd: info[nd["id"]] = stock_moves.item_info(nd)
    log = stock_moves.load(r_dir, key); moved = []
    for it in cand:
        sh, bk = lv[it]
        res = gql(MOVE, {"key": str(uuid.uuid4()), "input": {"name": "available", "reason": "movement_created",
              "referenceDocumentUri": "indifeels://restock/auto", "changes": [
              {"inventoryItemId": it, "locationId": BACKUP, "delta": -1, "changeFromQuantity": bk},
              {"inventoryItemId": it, "locationId": SHOPLOC, "delta": 1, "changeFromQuantity": sh}]}})
        errs = res["data"]["inventoryAdjustQuantities"]["userErrors"]
        if errs:
            print("skip move", it, errs[0].get("message")); continue
        lv[it] = [sh + 1, bk - 1]
        stock_moves.record(log, it, info.get(it, {}), sh + 1, bk - 1, os.environ.get("ORDER", ""))
        moved.append(it)
    for m in log["moves"]:
        if m["item"] in lv: log["now"][m["item"]] = {"shop": lv[m["item"]][0], "backup": lv[m["item"]][1]}
    stock_moves.save(r_dir, key, log)
    print(f"moved: {len(moved)}")
    # report reflects stock after the moves
    for f in os.listdir(data): os.remove(os.path.join(data, f))
    nodes = [{"q": [{"quantity": bk}], "item": {"id": i, "s": {"q": [{"quantity": sh}]}}} for i, (sh, bk) in lv.items()]
    json.dump({"data": {"location": {"inventoryLevels": {"nodes": nodes}}}}, open(os.path.join(data, "stock_levels_01.json"), "w"))
    ids = json.loads(subprocess.check_output([sys.executable, os.path.join(T, "stock.py"), "ids", data]))
    for i in range(0, len(ids), 100):
        json.dump(gql(ITEMS, {"ids": ids[i:i + 100]}), open(os.path.join(data, f"stock_items_{i // 100 + 1}.json"), "w"))
    env = dict(os.environ, SUMMARY_DIR=summ)
    print(subprocess.check_output([sys.executable, os.path.join(T, "stock.py"), "build", data, os.path.join(hub, "stock.html")], env=env, text=True).strip())
    subprocess.run([sys.executable, os.path.join(T, "encrypt.py"), json.dumps({"stock": key}), summ, hub, r_dir], check=True)
    print(f"pages: {n}, matches: {len(ids)}")


if __name__ == "__main__":
    try:
        main(); status(True)
    except Exception as e:
        status(False, f"Order-triggered stock refresh failed: {e}. Fix: check the SHOPIFY_TOKEN secret and the Actions log.")
        print("FAILED:", e); sys.exit(1)
