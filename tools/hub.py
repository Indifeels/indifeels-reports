"""Builds the Indifeels reports hub.
Usage: python3 hub.py SUMMARY_DIR HUB_DIR
SUMMARY_DIR holds daily.json / monthly.json written by build.py and monthly.py (SUMMARY_DIR env var).
HUB_DIR holds daily.html, monthly.html and stock.html; this writes HUB_DIR/index.html and adds a back link to each report page.
"""
import json, os, sys, html
SUM, HUB = sys.argv[1], sys.argv[2]

def load(n):
    p = os.path.join(SUM, n + ".json")
    return json.load(open(p)) if os.path.exists(p) else None

def money(v, dp=0):
    if v is None: return "—"
    return ("−" if v < 0 else "") + (f"${abs(v):,.{dp}f}")

SIGC = {"up": "scale", "hold": "hold", "down": "cut"}
d, m, k = load("daily"), load("monthly"), load("stock")

def stat(v, lab): return f'<div class="st"><b>{v}</b><span>{lab}</span></div>'
def pill(s):
    if not s or not s.get("sig"): return ""
    return f'<p class="sig"><span class="pl {SIGC[s["sig"]]}">{html.escape(s["sig_label"])}</span>{html.escape(s["reason"])}</p>'

tiles = []
if d:
    tiles.append(f'''<a class="tile" href="daily.html">
<h2>Non-tracked campaigns, daily</h2>
<p class="ds">Spend, messages and cost per message by campaign for today, this week, this month and lifetime, with FB sales, ROAS and orders still to attribute.</p>
<div class="sts">{stat(money(d["t_s"],2), "spent today")}{stat(f'{int(d["t_m"])}', "messages today")}{stat(money(d["m_sales"]), "FB sales this month")}{stat(f'{d["m_roas"]:.2f}x' if d["m_roas"] else "—", "ROAS this month")}</div>
{pill(d)}
<div class="ft"><span>Updated {html.escape(d["updated"])}{f' &nbsp;<em class="warn">{d["unatt"]} orders need a source</em>' if d.get("unatt") else ""}</span><span class="go">Open report</span></div></a>''')
if m:
    tiles.append(f'''<a class="tile" href="monthly.html">
<h2>Monthly profitability</h2>
<p class="ds">Spend, revenue, ROAS and net profit after GST, product cost and ads, month by month from {html.escape(m["since"])}, with daily detail and a scale / hold signal.</p>
<div class="sts">{stat(money(m["np"]), f'net profit, {html.escape(m["month"])}')}{stat(f'{m["roas"]:.2f}x', "ROAS this month")}{stat(money(m["spend"]), "spend this month")}{stat(money(m["total_np"]), f'net profit since {html.escape(m["since"])}')}</div>
{pill(m)}
<div class="ft"><span>Updated {html.escape(m["updated"])}</span><span class="go">Open report</span></div></a>''')
if k:
    tiles.append(f'''<a class="tile" href="stock.html">
<h2>Shop restock from Backup</h2>
<p class="ds">Variants with no stock at Shop location that have stock at Backup, with image, product, variant and both stock counts.</p>
<div class="sts">{stat(k["variants"], "variants to move")}{stat(k["units"], "units at Backup")}{stat(k["products"], "products")}</div>
<div class="ft"><span>Updated {html.escape(k["updated"])}</span><span class="go">Open report</span></div></a>''')

upd = (d or m or k or {}).get("updated", "")
page = f'''<title>Indifeels Reports</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#F6F7F9;--card:#FFFFFF;--ink:#101828;--muted:#5A6272;--line:#D9DEE6;--sub:#EEF1F5;--mari:#E8A317;--acc:#1D4ED8;
--g:#17694A;--gb:#D5F2E3;--y:#7A4E00;--yb:#FFEDBF;--r:#A8231B;--rb:#FFE0DC}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--acc:#8FB2FF;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--acc:#8FB2FF;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--ink);font:400 15px/1.5 Figtree,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding-inline:16px;padding-block:28px 48px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:22px}}
.hd{{border-left:6px solid var(--mari);padding-left:14px}}
h1{{font:700 clamp(26px,4.5vw,38px)/1.1 "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 6px;text-wrap:balance}}
.hd p{{margin:0;color:var(--muted);max-width:65ch}}
.tg{{flex:none;font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:7px 14px;cursor:pointer}}
.tg:focus-visible,.tile:focus-visible{{outline:3px solid var(--acc);outline-offset:2px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:16px}}
.tile{{display:flex;flex-direction:column;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;color:inherit;text-decoration:none;transition:border-color .15s,transform .15s}}
.tile:hover{{border-color:var(--acc)}}
@media (prefers-reduced-motion:no-preference){{.tile:hover{{transform:translateY(-2px)}}}}
.tile h2{{font:700 21px/1.2 "Bricolage Grotesque",Figtree,sans-serif;margin:0;text-wrap:balance}}
.ds{{margin:0;color:var(--muted);font-size:14px}}
.sts{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;padding-block:12px;border-block:1px solid var(--line)}}
@media (max-width:520px){{.sts{{grid-template-columns:repeat(2,1fr)}}}}
.st b{{display:block;font:700 20px/1.2 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums;white-space:nowrap}}
.st span{{font-size:12.5px;color:var(--muted)}}
.sig{{margin:0;font-size:13.5px;color:var(--muted);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.pl{{display:inline-block;font-weight:700;font-size:12.5px;padding:1px 9px;border-radius:99px;margin-right:8px}}
.pl.scale{{background:var(--gb);color:var(--g)}}.pl.hold{{background:var(--yb);color:var(--y)}}.pl.cut{{background:var(--rb);color:var(--r)}}
.ft{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--muted)}}
.warn{{font-style:normal;color:var(--r);font-weight:600}}
.go{{font-weight:700;color:var(--acc)}}
.note{{margin:18px 2px 0;color:var(--muted);font-size:13.5px;max-width:70ch}}
</style>
<main>
<header><div class="hd"><h1>Indifeels reports</h1><p>Meta messaging campaigns and Facebook-attributed Shopify sales, refreshed every night at 10 pm Sydney time. Last update {html.escape(upd)}.</p></div>
<button class="tg" id="tg" type="button">Dark mode</button></header>
<section class="grid">{"".join(tiles)}</section>
<p class="note">Open a report for the full detail. New reports are added here as tiles, so this one link always has everything.</p>
</main>
<script>
(function(){{var r=document.documentElement,b=document.getElementById('tg');
function cur(){{var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
function lab(){{b.textContent=cur()==='dark'?'Light mode':'Dark mode'}}
try{{var s=localStorage.getItem('ntr-theme');if(s)r.setAttribute('data-theme',s)}}catch(e){{}}
lab();b.addEventListener('click',function(){{var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{{localStorage.setItem('ntr-theme',n)}}catch(e){{}}lab()}});}})();
</script>'''
open(os.path.join(HUB, "index.html"), "w").write(page)

BACK = '<a href="./" style="display:inline-block;margin:0 0 14px;font:600 13.5px Figtree,system-ui,sans-serif;color:var(--muted);text-decoration:none">&larr; All reports</a>'
for fn in ("daily.html", "monthly.html", "stock.html"):
    p = os.path.join(HUB, fn)
    if not os.path.exists(p): continue
    s = open(p).read()
    if "All reports</a>" not in s:
        s = s.replace("<main>", "<main>" + BACK, 1)
    open(p, "w").write(s)
print("hub built:", len(tiles), "tiles")
