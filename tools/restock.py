"""Build the encrypted Restock report for the Indifeels dashboard.

Sold units per variant (order-by-order for the last 90 days, so the page can total any start date) (Shopify orders, cancelled excluded),
joined with current stock, product image and collections. Rows with no sales are omitted.

Cleared items: a row that was deleted or confirmed in the report is stored in Supabase
(restock_cleared) with the data cut-off the user was looking at. Only orders created AFTER that
cut-off are counted for that variant, so nothing is fetched twice and a cleared item reappears
only when it sells again, with just the new sales.

Runs after every Shopify order (repository_dispatch) and at 7am / 3pm / 8pm.

Env: SHOPIFY_TOKEN, SHOPIFY_SHOP, STOCK_KEY, SYNC_READ_TOKEN
Writes: r/restock.bin, r/restock.meta.bin, r/status.json
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import product_visibility as pv  # reuse gql, encrypt, write_encrypted, set_status

RID = "restock"
TZ = ZoneInfo("Australia/Sydney")
NOW = dt.datetime.now(TZ)
# Data cut-off: orders newer than this are left for the next build, so every order is counted once
# and the cut-off the page shows is also the watermark used when an item is cleared.
CUT = NOW.astimezone(dt.timezone.utc) - dt.timedelta(seconds=20)
SHEET_URL = os.environ.get("RESTOCK_SHEET_URL", "https://docs.google.com/spreadsheets/d/1YF_K9jObp1WqQ-HZZWSXwWaaFh6-UyOJE-d2AsmWOVs/edit")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://yrigvovwyfpaybibfjva.supabase.co")
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_8xv46B6mvnAN2McGDc4VEg_pNF0qHvD")  # public publishable key, same as the other builders

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
      product{title handle status featuredMedia{preview{image{url}}} collections(first:25){nodes{title}}}
    }
  }
}
"""


def parse_ts(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def load_cleared():
    """{variant numeric id: cleared_at (aware datetime)}. Fails the build if unreadable, so the last
    good report stays published instead of showing items that were already cleared."""
    token = os.environ["SYNC_READ_TOKEN"]
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/sync_get_restock_cleared",
        data=json.dumps({"p_token": token}).encode(),
        headers={"Content-Type": "application/json", "apikey": SUPABASE_ANON},
        method="POST",
    )
    rows = json.load(urllib.request.urlopen(req, timeout=60))
    return {str(r["vid"]): parse_ts(r["cleared_at"]) for r in rows}


HISTORY_DAYS = 90   # how far back the report's start date can go


def sold_by_variant(cleared):
    """({variant gid: [[order epoch seconds, units], ...]}, latest order epoch).
    Only orders after the variant's cleared_at and not newer than the data cut-off are included, so the report can
    total any start/end range in the page without fetching anything twice."""
    since = (CUT - dt.timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"created_at:>={since}"
    out = defaultdict(list)
    latest = 0
    after = None
    while True:
        d = pv.gql(ORDERS, {"after": after, "q": q})["data"]["orders"]
        for o in d["nodes"]:
            if o.get("cancelledAt"):
                continue
            at = parse_ts(o["createdAt"])
            if at > CUT:
                continue
            ts = int(at.timestamp())
            latest = max(latest, ts)
            per = defaultdict(int)
            for li in o["lineItems"]["nodes"]:
                v = (li.get("variant") or {}).get("id")
                n = int(li.get("quantity") or 0)
                if not v or n <= 0:
                    continue
                mark = cleared.get(v.rsplit("/", 1)[-1])
                if mark and at <= mark:
                    continue
                per[v] += n
            for v, n in per.items():
                out[v].append([ts, n])
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    for v in out:
        out[v].sort()
    return out, latest


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
    cleared = load_cleared()
    sold, latest = sold_by_variant(cleared)
    info = variant_details(sold.keys())
    rows = []
    for vid, s in sold.items():
        n = info.get(vid)
        if not n:
            continue
        p = n["product"]
        img = (n.get("image") or {}).get("url") or (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url") or ""
        cols = sorted({c["title"] for c in ((p.get("collections") or {}).get("nodes") or []) if c.get("title")})
        url = ("https://indifeels.com/products/" + p["handle"]) if p.get("handle") else ""
        rows.append([p["title"], n["title"], int(n.get("inventoryQuantity") or 0), thumb(img), s, vid.rsplit("/", 1)[-1], cols, url])
    # default order: out of stock first, then biggest shortfall over the last 30 days (the page can re-sort)
    c30 = int((CUT - dt.timedelta(days=30)).timestamp())
    sold30 = lambda r: sum(q for t, q in r[4] if t >= c30)
    rows.sort(key=lambda r: (r[2] > 0, -(sold30(r) - r[2]), r[0], r[1]))
    tpl = open(os.path.join(pv.ROOT, "tools", "restock_template.html"), encoding="utf-8").read()
    updated = NOW.strftime("%d %b %Y, %H:%M")
    asof_iso = CUT.strftime("%Y-%m-%dT%H:%M:%SZ")
    page = (tpl.replace("__DATA__", json.dumps(rows, ensure_ascii=False).replace("</", "<\\/"))
               .replace("__ASOFISO__", asof_iso)
               .replace("__LATEST__", str(latest or int(CUT.timestamp())))
               .replace("__HIST__", str(HISTORY_DAYS))
               .replace("__ASOF__", f"Shopify sales · updated {updated}")
               .replace("__SHEET__", SHEET_URL))
    live = [r for r in rows if sold30(r) > 0]
    out = sum(1 for r in live if r[2] <= 0)
    low = sum(1 for r in live if 0 < r[2] < sold30(r))
    meta = {
        "updated": updated,
        "stats": [[str(len(live)), "variants sold (30d)"], [str(out), "out of stock"], [str(low), "running low"]],
        "warn": f"{out} sold-out variants need restocking" if out else "",
    }
    key = os.environ["STOCK_KEY"]
    pv.write_encrypted(key, f"{RID}.bin", page.encode())
    pv.write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    pv.RID = RID
    pv.set_status(True)
    print(json.dumps({"variants": len(rows), "latest_order": latest, "out": out, "low": low, "cleared": len(cleared), "cutoff": asof_iso}))


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
