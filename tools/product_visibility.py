"""Build the encrypted Product visibility report for the Indifeels dashboard.

Section 1: UNLISTED products with stock available.
Section 2: ACTIVE products with stock where one or more merchant sales channels are off.

Env:
  SHOPIFY_TOKEN  Admin API token with read_products access
  SHOPIFY_SHOP   myshopify domain
  STOCK_KEY      base64 AES-256 key reused from the Stock report access group

Writes:
  r/product-visibility.bin
  r/product-visibility.meta.bin
  r/status.json
"""
import base64
import datetime as dt
import gzip
import html
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
RID = "product-visibility"
NOW = dt.datetime.now(ZoneInfo("Australia/Sydney"))

PRODUCTS = """
query ProductVisibility($after:String,$q:String!){
  products(first:100,after:$after,query:$q,sortKey:TITLE){
    pageInfo{hasNextPage endCursor}
    nodes{
      id title handle status totalInventory onlineStoreUrl publishedAt
      featuredMedia{preview{image{url}}}
      variants(first:100){nodes{id title sku inventoryQuantity}}
      collections(first:50){nodes{id title handle}}
    }
  }
}
"""

SALES_CHANNEL_FILTERS = [
    ("Online Store", "published_status:unpublished"),
    ("Shop", "published_status:shop-72-hidden"),
    ("Point of Sale", "published_status:pos-hidden"),
    ("Google & YouTube", "published_status:google-hidden"),
    ("Facebook & Instagram", "published_status:facebook-ads-hidden"),
]


SCOPES = """query VisibilityFixScopes { currentAppInstallation { accessScopes { handle } } }"""

def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(5):
        req = urllib.request.Request(
            API,
            body,
            {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": os.environ["SHOPIFY_TOKEN"],
            },
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


def fix_available():
    try:
        rows = gql(SCOPES, {})["data"]["currentAppInstallation"]["accessScopes"]
        scopes = {x["handle"] for x in rows}
        return {"write_products", "write_publications"}.issubset(scopes)
    except Exception:
        return False


def fetch_products(search):
    rows, after = [], None
    while True:
        data = gql(PRODUCTS, {"after": after, "q": search})["data"]["products"]
        rows.extend(data["nodes"])
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


def e(value):
    return html.escape(str(value or ""), quote=True)


def in_stock_variants(product):
    return [
        v
        for v in product.get("variants", {}).get("nodes", [])
        if (v.get("inventoryQuantity") or 0) > 0
    ]


def channel_issue_products():
    """Return active in-stock products grouped with merchant sales channels that are off.

    Uses Shopify's published_status product-search filter, which only requires read_products.
    """
    merged = {}
    for channel, visibility_filter in SALES_CHANNEL_FILTERS:
        for product in fetch_products(f"status:active inventory_total:>0 {visibility_filter}"):
            row = merged.setdefault(product["id"], {"product": product, "channels": []})
            if channel not in row["channels"]:
                row["channels"].append(channel)
    return sorted(
        [(row["product"], row["channels"]) for row in merged.values()],
        key=lambda x: (x[0].get("title") or "").lower(),
    )


def admin_url(product):
    numeric = product["id"].rsplit("/", 1)[-1]
    store_handle = SHOP.split(".", 1)[0]
    return f"https://admin.shopify.com/store/{store_handle}/products/{numeric}"


def image_url(product):
    return (
        (((product.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url")
        or ""
    )


def variant_chips(product):
    vals = in_stock_variants(product)
    if not vals:
        return '<span class="muted">No positive-stock variant returned</span>'
    return "".join(
        f'<span class="chip"><b>{e(v.get("title") or "Default")}</b><span>× {int(v.get("inventoryQuantity") or 0)}</span></span>'
        for v in vals
    )


def product_collections(product):
    return sorted(
        product.get("collections", {}).get("nodes", []),
        key=lambda x: (x.get("title") or "").lower(),
    )


def collection_chips(product):
    vals = product_collections(product)
    if not vals:
        return '<span class="muted">No collection assigned</span>'
    return "".join(f'<span class="chip">{e(x.get("title") or "Untitled")}</span>' for x in vals)


def product_card(product, channels=None, issue="channels", fix_ready=True):
    img = image_url(product)
    thumb = (
        f'<img src="{e(img + ("&" if "?" in img else "?") + "width=220")}" alt="" loading="lazy">'
        if img
        else '<span class="ph">No image</span>'
    )
    channels = channels or []
    channel_html = (
        '<div class="channels"><span class="label">Channels off</span>'
        + "".join(f'<span class="bad">{e(c)}</span>' for c in channels)
        + "</div>"
        if channels
        else ""
    )
    website = product.get("onlineStoreUrl")
    website_link = (
        f'<a class="small-link" href="{e(website)}" target="_blank" rel="noopener">View product</a>'
        if website
        else ""
    )
    cols = product_collections(product)
    col_ids = "|".join(x.get("id") or "" for x in cols)
    search_text = " ".join(
        [
            product.get("title") or "",
            product.get("handle") or "",
            " ".join(v.get("title") or "" for v in in_stock_variants(product)),
            " ".join(channels),
            " ".join(x.get("title") or "" for x in cols),
            "unlisted" if issue == "unlisted" else "channel off",
        ]
    ).lower()
    issue_badge = '<span class="issue unlisted">UNLISTED</span>' if issue == "unlisted" else '<span class="issue channel">CHANNEL OFF</span>'
    return f"""<article class="item" data-search="{e(search_text)}" data-collections="{e(col_ids)}">
      <div class="pic">{thumb}</div>
      <div class="main">
        <div class="name-row">
          <div>
            <div class="badges">{issue_badge}</div>
            <a class="name" href="{e(admin_url(product))}" target="_blank" rel="noopener">{e(product.get("title"))}</a>
            <div class="links">{website_link}<a class="small-link" href="{e(admin_url(product))}" target="_blank" rel="noopener">Open in Shopify</a></div>
          </div>
          <span class="stock">{int(product.get("totalInventory") or 0)} in stock</span>
        </div>
        {channel_html}
        <div class="variants"><span class="label">In-stock variants</span>{variant_chips(product)}</div>
        <div class="collections"><span class="label">Collections</span>{collection_chips(product)}</div>
        <div class="actions"><button class="fix-one" type="button" data-product-id="{e(product.get("id"))}" {"disabled" if not fix_ready else ""}>Fix Now</button></div>
      </div>
    </article>"""

def encrypt(key_b64, payload):
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise RuntimeError("STOCK_KEY is not a 32-byte AES key")
    iv = os.urandom(12)
    cipher = AESGCM(key).encrypt(iv, gzip.compress(payload, 9), None)
    return iv + cipher


def write_encrypted(key_b64, filename, payload):
    os.makedirs(RDIR, exist_ok=True)
    with open(os.path.join(RDIR, filename), "wb") as f:
        f.write(encrypt(key_b64, payload))


def set_status(ok, reason=""):
    subprocess.run(
        [
            sys.executable,
            os.path.join(TOOLS, "status.py"),
            RDIR,
            RID,
            "ok" if ok else "fail",
            reason,
        ],
        check=True,
    )


def build():
    fix_ready = fix_available()
    unlisted = fetch_products("status:unlisted inventory_total:>0")
    channel_rows = channel_issue_products()
    channel_counter = Counter()
    for _, channels in channel_rows:
        channel_counter.update(channels)

    unlisted_units = sum(int(p.get("totalInventory") or 0) for p in unlisted)
    channel_units = sum(int(p.get("totalInventory") or 0) for p, _ in channel_rows)
    updated = NOW.strftime("%d %b %Y, %H:%M")

    all_products = list(unlisted) + [p for p, _ in channel_rows]
    collection_map = {}
    for product in all_products:
        for col in product_collections(product):
            if col.get("id"):
                collection_map[col["id"]] = col.get("title") or "Untitled"
    collection_options = "".join(
        f'<option value="{e(cid)}">{e(title)}</option>'
        for cid, title in sorted(collection_map.items(), key=lambda x: x[1].lower())
    )

    section1 = (
        "".join(product_card(p, issue="unlisted", fix_ready=fix_ready) for p in unlisted)
        if unlisted
        else '<p class="empty good">No unlisted products currently have stock.</p>'
    )
    section2 = (
        "".join(product_card(p, channels, issue="channels", fix_ready=fix_ready) for p, channels in channel_rows)
        if channel_rows
        else '<p class="empty good">All active in-stock products are published to the checked sales channels.</p>'
    )

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Product visibility</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#151922;--muted:#68707d;--line:#e2e5ea;--soft:#f0f2f5;--red:#b42318;--redbg:#fff0ee;--green:#147a50;--greenbg:#eaf8f1;--blue:#2356a8}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0e1116;--card:#171b22;--ink:#edf0f4;--muted:#a0a8b6;--line:#2a303b;--soft:#1f242d;--red:#ff9a8f;--redbg:#3a1d1a;--green:#78d9ad;--greenbg:#133326;--blue:#8bb8ff}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1050px;margin:auto;padding:24px 14px 48px}} h1{{font-size:30px;line-height:1.15;margin:0 0 6px}} h2{{font-size:22px;margin:28px 0 6px}} p{{margin:0}}
.lead,.sub,.muted{{color:var(--muted)}} .lead{{max-width:760px}} .sub{{font-size:13.5px;margin-bottom:12px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0 8px}} .kpi{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 14px}}
.kpi b{{display:block;font-size:24px}} .kpi span{{color:var(--muted);font-size:12.5px}}
.tools{{display:grid;grid-template-columns:minmax(180px,260px) 1fr auto;gap:8px;margin:18px 0 4px}}
.tools input,.tools select{{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);font:inherit}}
.tools button,.fix-one{{border:0;border-radius:10px;background:var(--blue);color:#fff;font:700 13px/1 system-ui;padding:11px 14px;cursor:pointer}}
.tools button:disabled,.fix-one:disabled{{opacity:.55;cursor:default}}
.fix-note{{margin:9px 2px 0;color:var(--muted);font-size:13px}}
.badges{{margin-bottom:4px}} .issue{{display:inline-block;border-radius:999px;padding:3px 7px;font-size:10.5px;font-weight:800;letter-spacing:.04em}}
.issue.unlisted{{background:var(--redbg);color:var(--red)}} .issue.channel{{background:var(--soft);color:var(--muted);border:1px solid var(--line)}}
.collections{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}} .collections .label{{flex-basis:100%;margin-bottom:0}}
.actions{{display:flex;justify-content:flex-end;margin-top:10px}}
.list{{display:grid;gap:10px}} .item{{display:grid;grid-template-columns:88px 1fr;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px}}
.pic img,.ph{{display:flex;width:88px;height:108px;object-fit:cover;border-radius:9px;background:var(--soft);align-items:center;justify-content:center;color:var(--muted);font-size:11px;text-align:center}}
.main{{min-width:0}} .name-row{{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}} .name{{font-weight:750;color:var(--ink);text-decoration:none;font-size:16px}}
.links{{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}} .small-link{{color:var(--blue);text-decoration:none;font-size:12.5px}} .stock{{white-space:nowrap;background:var(--greenbg);color:var(--green);font-weight:700;font-size:12px;padding:4px 8px;border-radius:999px}}
.label{{display:block;color:var(--muted);font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin:9px 0 5px}}
.variants,.channels{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}} .variants .label,.channels .label{{flex-basis:100%;margin-bottom:0}}
.chip{{display:inline-flex;gap:5px;align-items:center;background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:3px 7px;font-size:12.5px}} .chip span{{color:var(--muted)}} .bad{{background:var(--redbg);color:var(--red);border-radius:8px;padding:4px 7px;font-size:12px;font-weight:700}}
.empty{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;color:var(--muted)}} .empty.good{{color:var(--green)}}
.note{{margin-top:16px;color:var(--muted);font-size:12.5px}}
.hidden{{display:none!important}}
@media(max-width:680px){{.kpis{{grid-template-columns:repeat(2,1fr)}} .tools{{grid-template-columns:1fr}} .item{{grid-template-columns:68px 1fr}} .pic img,.ph{{width:68px;height:86px}} .name-row{{display:block}} .stock{{display:inline-block;margin-top:6px}} h1{{font-size:26px}}}}
</style></head><body><main>
<h1>Product visibility</h1>
<p class="lead">Products that can be missed because they are unlisted or because a sales channel is switched off. Only products with stock are included.</p>
<div class="kpis">
  <div class="kpi"><b>{len(unlisted)}</b><span>unlisted products with stock</span></div>
  <div class="kpi"><b>{unlisted_units}</b><span>units on unlisted products</span></div>
  <div class="kpi"><b>{len(channel_rows)}</b><span>products with a channel off</span></div>
  <div class="kpi"><b>{channel_units}</b><span>units on channel-issue products</span></div>
</div>
<div class="tools">
  <select id="collection-filter" aria-label="Filter by collection"><option value="">All collections</option>{collection_options}</select>
  <input id="q" type="search" placeholder="Search product, variant or channel…" aria-label="Search report">
  <button id="fix-all" type="button" {"disabled" if not fix_ready else ""}>Fix All</button>
</div>
<p id="fix-note" class="fix-note" {"hidden" if fix_ready else ""}>{"Fix buttons are ready." if fix_ready else "Fix buttons need the Shopify write_publications permission before they can safely turn every sales channel on."}</p>

<section><h2>1. Unlisted products with stock</h2><p class="sub">Shopify status is UNLISTED and at least one variant has stock.</p><div class="list">{section1}</div></section>
<section><h2>2. Listed products with a sales channel off</h2><p class="sub">Active products with stock where Online Store or another merchant sales channel is not published.</p><div class="list">{section2}</div></section>
<p class="note">Updated {e(updated)} Australia/Sydney. Inbox and Shopify GraphiQL App are ignored because they are utility/app publications, not storefront sales channels.</p>
<script>
const q=document.getElementById("q"), cf=document.getElementById("collection-filter"), note=document.getElementById("fix-note");
function applyFilters(){{
  const s=q.value.trim().toLowerCase(), col=cf.value;
  document.querySelectorAll(".item").forEach(x=>{{
    const textOk=!s || x.dataset.search.includes(s);
    const cols=(x.dataset.collections||"").split("|");
    const colOk=!col || cols.includes(col);
    x.classList.toggle("hidden",!(textOk&&colOk));
  }});
}}
q.addEventListener("input",applyFilters); cf.addEventListener("change",applyFilters);
function startFix(action, productId, button){{
  if(button){{button.disabled=true;button.dataset.old=button.textContent;button.textContent="Fixing…";}}
  note.hidden=false; note.textContent=action==="fix-all"?"Fix All started…":"Fix started…";
  window.parent.postMessage({{type:"product-visibility-fix",action,product_id:productId||null}},"*");
}}
document.querySelectorAll(".fix-one").forEach(b=>b.addEventListener("click",()=>startFix("fix-one",b.dataset.productId,b)));
document.getElementById("fix-all").addEventListener("click",e=>startFix("fix-all",null,e.currentTarget));
window.addEventListener("message",e=>{{
  const d=e.data||{{}}; if(d.type!=="product-visibility-fix-result") return;
  note.hidden=false; note.textContent=d.ok ? (d.message||"Fix started. The report will refresh automatically.") : (d.error||"Fix could not be started.");
  if(!d.ok) document.querySelectorAll(".fix-one,#fix-all").forEach(b=>{{b.disabled=false;b.textContent=b.dataset.old||b.textContent;}});
}});
</script>
</main></body></html>"""

    meta = {
        "updated": updated,
        "stats": [
            [str(len(unlisted)), "unlisted with stock"],
            [str(unlisted_units), "units unlisted"],
            [str(len(channel_rows)), "products with channel off"],
            [str(len(channel_counter)), "channels affected"],
        ],
        "warn": (
            f"{len(unlisted) + len(channel_rows)} products need a visibility check"
            if unlisted or channel_rows
            else ""
        ),
    }

    key = os.environ["STOCK_KEY"]
    write_encrypted(key, f"{RID}.bin", page.encode())
    write_encrypted(key, f"{RID}.meta.bin", json.dumps(meta).encode())
    print(
        json.dumps(
            {
                "unlisted_products": len(unlisted),
                "unlisted_units": unlisted_units,
                "channel_issue_products": len(channel_rows),
                "channel_counts": dict(channel_counter),
                "fix_available": fix_ready,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        build()
        set_status(True)
    except Exception as exc:
        set_status(False, f"Product visibility refresh failed: {exc}. Check Shopify token/scopes and the Actions log.")
        print("FAILED:", exc)
        raise
