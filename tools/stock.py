"""Shop restock report: variants with no stock at Shop location but stock at Backup.
Usage:
  python3 stock.py ids DATA_DIR
      Reads DATA_DIR/stock_levels*.json (Backup location inventoryLevels pages) and prints the
      JSON list of inventory item ids to look up next.
  SUMMARY_DIR=<dir> python3 stock.py build DATA_DIR OUT_HTML
      Reads the same pages plus DATA_DIR/stock_items*.json (nodes(ids:) lookup) and writes the report
      page and SUMMARY_DIR/stock.json.
Page query (Backup location, 250 per page):
  { location(id:"gid://shopify/Location/99841048933") { inventoryLevels(first:250, after:CURSOR) {
      pageInfo { hasNextPage endCursor }
      nodes { q: quantities(names:["available"]) { quantity }
              item { id s: inventoryLevel(locationId:"gid://shopify/Location/99623436645") { q: quantities(names:["available"]) { quantity } } } } } } }
Items query:
  { nodes(ids:[...]) { ... on InventoryItem { id sku variant { title image { url } product { title status featuredMedia { preview { image { url } } } } } } } }
"""
import json, html, glob, os, sys, datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Sydney")
NOW = dt.datetime.now(TZ)
if os.environ.get("REPORT_NOW"): NOW = dt.datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)


def unwrap(x):
    if isinstance(x, str): x = json.loads(x)
    if isinstance(x, dict) and "result" in x: x = x["result"]
    if isinstance(x, list) and x and isinstance(x[0], dict) and "text" in x[0]: x = json.loads(x[0]["text"])
    if isinstance(x, str): x = json.loads(x)
    return x


def qty(q):
    if not isinstance(q, list) or not q: return 0
    return q[0].get("quantity") or 0


def levels(d):
    out = {}
    for f in sorted(glob.glob(f"{d}/stock_levels*")):
        x = unwrap(json.load(open(f)))
        for n in x["data"]["location"]["inventoryLevels"]["nodes"]:
            it = n["item"]
            out[it["id"]] = (qty((it.get("s") or {}).get("q")), qty(n.get("q")))
    return out


def matches(d):
    return {k: v for k, v in levels(d).items() if v[0] <= 0 and v[1] > 0}


mode, D = sys.argv[1], sys.argv[2]
M = matches(D)
if mode == "ids":
    print(json.dumps(sorted(M)))
    sys.exit()

OUT = sys.argv[3]
items = {}
for f in sorted(glob.glob(f"{D}/stock_items*")):
    for n in unwrap(json.load(open(f)))["data"]["nodes"]:
        if n: items[n["id"]] = n
rows = []
for iid, (shop, backup) in M.items():
    n = items.get(iid) or {}
    v = n.get("variant") or {}
    p = v.get("product") or {}
    img = (v.get("image") or {}).get("url") or (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url") or ""
    vt = v.get("title") or ""
    rows.append(dict(img=img, name=p.get("title") or "(unknown product)", variant="" if vt == "Default Title" else vt,
                     sku=n.get("sku") or "", status=(p.get("status") or "").title(), shop=shop, backup=backup))
rows.sort(key=lambda r: (r["name"].lower(), r["variant"]))
units = sum(r["backup"] for r in rows)
prods = len({r["name"] for r in rows})
UPD = NOW.strftime("%a %-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
e = html.escape


def thumb(u):
    if not u: return '<div class="ph" aria-hidden="true"></div>'
    src = u + ("&" if "?" in u else "?") + "width=160"
    return f'<a href="{e(u)}" target="_blank" rel="noopener"><img src="{e(src)}" alt="" loading="lazy" width="72" height="90"></a>'


trs = "".join(
    f'<tr><td class="im">{thumb(r["img"])}</td><td><b>{e(r["name"])}</b>'
    f'<span class="vm">{e(r["variant"]) or "—"}</span><span class="sub">{e(r["sku"])}{" · " + e(r["status"]) if r["status"] and r["status"] != "Active" else ""}</span></td>'
    f'<td class="vc">{e(r["variant"]) or "—"}</td><td class="n zero">{r["shop"]}</td><td class="n pos">{r["backup"]}</td></tr>'
    for r in rows)
body = (f'<div class="tw"><table><thead><tr><th scope="col"><span class="vh">Image</span></th><th scope="col">Product</th>'
        f'<th scope="col" class="vc">Variant</th><th scope="col" class="n">Shop location</th><th scope="col" class="n">Backup</th></tr></thead>'
        f'<tbody>{trs}</tbody></table></div>') if rows else '<p class="empty">Nothing to move. Every variant with Backup stock also has stock at Shop location.</p>'

DK = "color-scheme:dark;--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--r:#FF8C80;--rb:#3D1A17"
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Shop restock from Backup</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#F6F7F9;--card:#FFF;--ink:#101828;--muted:#5A6272;--line:#D9DEE6;--sub:#EEF1F5;--mari:#E8A317;--g:#17694A;--gb:#D5F2E3;--r:#A8231B;--rb:#FFE0DC}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{DK}}}}}
:root[data-theme="dark"]{{{DK}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.5 Figtree,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 48px}}
.hd{{border-left:6px solid var(--mari);padding-left:14px;margin-bottom:18px}}
h1{{font:700 clamp(24px,4.5vw,34px)/1.15 "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 6px;text-wrap:balance}}
.hd p{{margin:0;color:var(--muted);max-width:65ch}}
.kp{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:0 0 16px}}
.kp div{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.kp b{{display:block;font:700 24px/1.2 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums}}
.kp span{{font-size:13px;color:var(--muted)}}
.tw{{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px 12px;text-align:left;vertical-align:middle;border-bottom:1px solid var(--line)}}
tbody tr:last-child td{{border-bottom:0}}
thead th{{font-size:12.5px;font-weight:600;color:var(--muted);background:var(--sub);white-space:nowrap}}
.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
td.n{{font:700 18px "Bricolage Grotesque",sans-serif}}
.zero{{color:var(--r)}}.pos{{color:var(--g)}}
.im{{width:88px;padding-right:0}}
.im img,.ph{{display:block;width:72px;height:90px;object-fit:cover;border-radius:8px;background:var(--sub)}}
.sub{{display:block;font-size:12.5px;color:var(--muted)}}
.vm{{display:none;margin-top:4px;font-weight:700;font-size:13px;background:var(--sub);border:1px solid var(--line);border-radius:6px;padding:1px 7px;width:max-content}}
.vc{{white-space:nowrap;font-weight:600}}
.vh{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}}
.empty{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:0}}
.note{{margin:14px 2px 0;color:var(--muted);font-size:13.5px}}
@media (max-width:560px){{.vc{{display:none}}.vm{{display:block}}thead th.n{{white-space:normal}}.kp b{{font-size:20px}}th,td{{padding:8px}}.im{{width:64px}}.im img,.ph{{width:56px;height:70px}}td.n{{font-size:16px}}}}
</style></head><body><main>
<div class="hd"><h1>Shop restock from Backup</h1><p>Variants with no stock at Shop location that have stock at Backup. Checked across every variant in Shopify. Updated {e(UPD)}.</p></div>
<div class="kp"><div><b>{len(rows)}</b><span>variants to move</span></div><div><b>{units}</b><span>units at Backup</span></div><div><b>{prods}</b><span>products</span></div></div>
{body}
<p class="note">Zero or negative stock at Shop location counts as out of stock. Tap an image to open it full size.</p>
</main></body></html>'''
open(OUT, "w").write(page)
json.dump(dict(updated=UPD, variants=len(rows), units=units, products=prods,
               top=[f'{r["name"]} {r["variant"]}'.strip() for r in rows[:3]]),
          open(os.path.join(os.environ["SUMMARY_DIR"], "stock.json"), "w"))
print(f"stock: {len(rows)} variants, {units} units")
