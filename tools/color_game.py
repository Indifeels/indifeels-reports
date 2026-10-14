"""Build the encrypted Colour Tagging Game report for the Indifeels dashboard.

Only LIVE products are included: Shopify status ACTIVE and at least one unit in stock.
Each product carries the colours already set in the shopify.color-pattern metafield,
so finished products show as done and the game only serves the ones still missing.

Env:
  SHOPIFY_TOKEN  Admin API token with read_products access (read_metaobjects is used when available)
  SHOPIFY_SHOP   myshopify domain
  STOCK_KEY      base64 AES-256 key reused from the Stock report access group

Writes:
  r/color-game.bin
  r/color-game.meta.bin
  r/status.json
"""
import base64
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RDIR = os.path.join(ROOT, "r")
TOOLS = os.path.join(ROOT, "tools")
SHOP = os.environ.get("SHOPIFY_SHOP", "bvdxj3-r8.myshopify.com")
API = f"https://{SHOP}/admin/api/2026-04/graphql.json"
RID = "color-game"
LIVE_QUERY = "status:active AND inventory_total:>0"
NOW = dt.datetime.now(ZoneInfo("Australia/Sydney"))
NOISE = ("do not delete", "filter index", "all products", "home page", "frontpage")

PRODUCTS = """
query ColorGame($after:String,$q:String!){
  products(first:100,after:$after,query:$q,sortKey:TITLE){
    pageInfo{hasNextPage endCursor}
    nodes{
      id title
      featuredMedia{preview{image{url}}}
      collections(first:30){nodes{title}}
      metafield(namespace:"shopify",key:"color-pattern"){jsonValue}
    }
  }
}
"""

COLOR_DEFS = """
query ColorDefs($after:String){
  metaobjects(type:"shopify--color-pattern",first:100,after:$after){
    pageInfo{hasNextPage endCursor}
    nodes{id handle displayName fields{key value}}
  }
}
"""

# Fallback when the token cannot read metaobjects: the Color list as of 14 Oct 2026.
FALLBACK_COLORS = [
    ("59255718245", "mint", "Mint", "#B5E3BD"), ("59283145061", "floral", "Floral", None),
    ("59283177829", "blue", "Sky Blue", "#99C3FA"), ("59283276133", "white", "White", "#FFFFFF"),
    ("59283308901", "beige", "Beige", "#EAD8AB"), ("59283603813", "rani", "Hot Pink", "#D846AE"),
    ("59300839781", "red", "Red", "#F61F1F"), ("59304608101", "green", "Green", "#05AA3D"),
    ("59305001317", "yellow", "Yellow", "#FFD000"),
    ("59305132389", "lavender", "Lavender", "#C5A5DF"), ("59305427301", "black", "Black", "#000000"),
    ("59305460069", "maroon", "Maroon", "#AC2020"), ("59305558373", "purple", "Purple", "#A54DCF"),
    ("59305918821", "cream", "Ivory", "#FCFAD9"), ("59305951589", "orange", "Orange", "#FF8A00"),
    ("59305984357", "teal", "Teal", "#20526F"), ("59306017125", "rose-gold", "Rose gold", "#B76E79"),
    ("59306049893", "peach", "Peach", "#FAB7A8"), ("59306082661", "wine", "Wine", "#771D4E"),
    ("59306148197", "brown", "Brown", "#9A5630"), ("59306180965", "pink-1", "Pink", "#FFC0CB"),
    ("59346813285", "blue-1", "Blue", "#005BD3"), ("59349238117", "gray", "Gray", "#808080"),
    ("59427422565", "gold", "Gold", "#D49A06"), ("59472609637", "multicolor", "Multicolor", None),
    ("59472773477", "grey", "Grey", "#808080"), ("59472871781", "silver", "Silver", "#D3D3D3"),
    ("59624685925", "aqua", "Aqua", "#8AEADD"), ("61222027621", "geometric", "Geometric", None),
    ("71808483685", "dots", "Dots", None), ("75614880101", "navy", "Navy", "#282099"),
]


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            API,
            body,
            {"Content-Type": "application/json", "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"]},
        )
        try:
            out = json.load(urllib.request.urlopen(req, timeout=90))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"Shopify API returned HTTP {exc.code}") from exc
        if out.get("errors"):
            if any("THROTTLED" in json.dumps(x) for x in out["errors"]) and attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError("Shopify query error: " + json.dumps(out["errors"])[:240])
        return out
    raise RuntimeError("Shopify API kept throttling")


def paged(query, variables, path):
    rows, after = [], None
    while True:
        data = gql(query, {**variables, "after": after})["data"]
        for key in path:
            data = data[key]
        rows.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


def load_colors():
    """Return list of {handle,label,hex,gid} in Shopify order."""
    try:
        nodes = paged(COLOR_DEFS, {}, ["metaobjects"])
        out = []
        for n in nodes:
            f = {x["key"]: x["value"] for x in n["fields"]}
            out.append({"handle": n["handle"], "label": f.get("label") or n["displayName"], "hex": f.get("color"), "gid": n["id"]})
        out = [c for c in out if c["handle"] != "navy-blue"]  # merged into Blue
        if out:
            return out, True
    except Exception as exc:  # token may not have read_metaobjects
        print("colour definitions fall back to the saved list:", exc)
    return [
        {"handle": h, "label": l, "hex": x, "gid": f"gid://shopify/Metaobject/{i}"} for i, h, l, x in FALLBACK_COLORS
    ], False


def img_url(url):
    if not url:
        return ""
    return url + ("&" if "?" in url else "?") + "width=640"


def write_encrypted(key_b64, name, data):
    key = base64.b64decode(key_b64)
    iv = os.urandom(12)
    os.makedirs(RDIR, exist_ok=True)
    with open(os.path.join(RDIR, name), "wb") as fh:
        fh.write(iv + AESGCM(key).encrypt(iv, gzip.compress(data, 9), None))


def set_status(ok, reason=""):
    args = [sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok" if ok else "fail"]
    if reason:
        args.append(reason[:240])
    subprocess.run(args, check=False)


def build():
    colors, from_shopify = load_colors()
    gid_to_handle = {c["gid"]: c["handle"] for c in colors}
    raw = paged(PRODUCTS, {"q": LIVE_QUERY}, ["products"])

    counts = Counter()
    products = []
    for p in raw:
        cols = [c["title"] for c in p["collections"]["nodes"] if not any(w in c["title"].lower() for w in NOISE)]
        counts.update(set(cols))
        mf = (p.get("metafield") or {}).get("jsonValue") or []
        existing = list(dict.fromkeys(gid_to_handle[g] for g in mf if g in gid_to_handle))
        image = ((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}
        products.append(
            {
                "id": p["id"].rsplit("/", 1)[-1],
                "title": p["title"],
                "cols": cols,
                "img": img_url(image.get("url")),
                "existing": existing,
            }
        )
    # keep only collections big enough to be useful as categories
    keep = {c for c, n in counts.items() if n >= 3}
    for p in products:
        p["cols"] = [c for c in p["cols"] if c in keep]

    page = open(os.path.join(TOOLS, "color_game_template.html"), encoding="utf-8").read()
    data = json.dumps({"colors": colors, "products": products}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    marker = '/*__DATA__*/{"colors":[],"products":[]}'
    if marker not in page:
        raise RuntimeError("template data marker is missing")
    page = page.replace(marker, data, 1)

    done = sum(1 for p in products if p["existing"])
    pending = len(products) - done
    pct = round(done / len(products) * 100) if products else 0
    updated = NOW.strftime("%d %b %Y, %-I:%M %p")
    meta = {
        "updated": updated,
        "stats": [[str(len(products)), "live products"], [str(pending), "still need a colour"], [f"{pct}%", "tagged"]],
        "warn": f"{pending} live products have no colour" if pending else "",
    }
    key = os.environ["STOCK_KEY"]
    write_encrypted(key, f"{RID}.bin", page.encode())
    write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    print(json.dumps({"live_products": len(products), "tagged": done, "pending": pending, "collections": len(keep), "colours": len(colors), "colours_from_shopify": from_shopify}, sort_keys=True))


if __name__ == "__main__":
    try:
        build()
        set_status(True)
    except Exception as exc:
        set_status(False, f"Colour game refresh failed: {exc}. Check Shopify token/scopes and the Actions log.")
        print("FAILED:", exc)
        raise
