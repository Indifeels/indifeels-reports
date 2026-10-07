"""Build the encrypted Restock report for the Indifeels dashboard.

Sold units per variant over the last 7/15/30 days (Shopify orders, cancelled excluded),
joined with current stock and product image. Rows with no sales in 30 days are omitted.

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY
Writes: r/restock.bin, r/restock.meta.bin, r/status.json
"""
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv  # reuse gql, encrypt, write_encrypted, set_status

RID = "restock"
NOW = dt.datetime.now(ZoneInfo("Australia/Sydney"))
SHEET_URL = os.environ.get("RESTOCK_SHEET_URL", "https://docs.google.com/spreadsheets/d/1YF_K9jObp1WqQ-HZZWSXwWaaFh6-UyOJE-d2AsmWOVs/edit")

ORDERS = """
query Orders($after:String,$q:String!){
  orders(first:100,after:$after,query:$q,sortKey:CREATED_AT){
    pageInfo{hasNextPage endCursor}
    nodes{
      createdAt cancelledAt
      lineItems(first:100){nodes{quantity refundableQuantity variant{id}}}
    }
  }
}
"""
VARIANTS = """
query V($ids:[ID!]!){
  nodes(ids:$ids){
    ... on ProductVariant{
      id title inventoryQuantity
      image{url}
      product{title status featuredMedia{preview{image{url}}}}
    }
  }
}
"""


def sold_by_variant():
    since = (NOW - dt.timedelta(days=30)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"created_at:>={since}"
    out = defaultdict(lambda: [0, 0, 0])
    after = None
    cut7 = NOW - dt.timedelta(days=7)
    cut15 = NOW - dt.timedelta(days=15)
    while True:
        d = pv.gql(ORDERS, {"after": after, "q": q})["data"]["orders"]
        for o in d["nodes"]:
            if o.get("cancelledAt"):
                continue
            at = dt.datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00"))
            for li in o["lineItems"]["nodes"]:
                v = (li.get("variant") or {}).get("id")
                n = int(li.get("quantity") or 0)
                if not v or n <= 0:
                    continue
                out[v][2] += n
                if at >= cut15:
                    out[v][1] += n
                if at >= cut7:
                    out[v][0] += n
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    return out


def variant_details(ids):
    info = {}
    ids = list(ids)
    for i in range(0, len(ids), 100):
        for n in pv.gql(VARIANTS, {"ids": ids[i:i + 100]})["data"]["nodes"]:
            if n:
                info[n["id"]] = n
    return info


def thumb(url):
    if not url:
        return ""
    return url + ("&" if "?" in url else "?") + "width=160"


def build():
    sold = sold_by_variant()
    info = variant_details(sold.keys())
    rows = []
    for vid, s in sold.items():
        n = info.get(vid)
        if not n:
            continue
        p = n["product"]
        img = (n.get("image") or {}).get("url") or (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url") or ""
        rows.append([p["title"], n["title"], int(n.get("inventoryQuantity") or 0), thumb(img), s[0], s[1], s[2], vid.rsplit("/", 1)[-1]])
    # most urgent first: out of stock, then biggest shortfall
    rows.sort(key=lambda r: (r[2] > 0, -(r[6] - r[2]), r[0], r[1]))
    tpl = open(os.path.join(pv.ROOT, "tools", "restock_template.html"), encoding="utf-8").read()
    updated = NOW.strftime("%d %b %Y, %H:%M")
    page = (tpl.replace("__DATA__", json.dumps(rows, ensure_ascii=False).replace("</", "<\\/"))
               .replace("__ASOF__", f"Shopify sales · updated {updated}")
               .replace("__SHEET__", SHEET_URL))
    out = sum(1 for r in rows if r[2] <= 0)
    low = sum(1 for r in rows if 0 < r[2] < r[6])
    meta = {
        "updated": updated,
        "stats": [[str(len(rows)), "variants sold (30d)"], [str(out), "out of stock"], [str(low), "running low"]],
        "warn": f"{out} sold-out variants need restocking" if out else "",
    }
    key = os.environ["STOCK_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"variants": len(rows), "out": out, "low": low}))


if __name__ == "__main__":
    pv.RID = RID
    try:
        build()
    except Exception as exc:
        pv.RID = RID
        try:
            pv.set_status(False, f"Restock build failed: {type(exc).__name__}")
        except Exception:
            pass
        raise
