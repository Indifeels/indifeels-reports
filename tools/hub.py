"""Builds the Indifeels reports hub (the Claude dashboard).
Usage: python3 hub.py SUMMARY_DIR HUB_DIR
SUMMARY_DIR holds daily.json / monthly.json / stock.json written by build.py, monthly.py and stock.py.
HUB_DIR holds daily.html, monthly.html and stock.html; this writes HUB_DIR/index.html and adds a back link to each report page.
Tile look matches the Indifeels Reports app (app.css / app.js tileHTML).
"""
import json, os, sys, html
SUM, HUB = sys.argv[1], sys.argv[2]
e = html.escape

def load(n):
    p = os.path.join(SUM, n + ".json")
    return json.load(open(p)) if os.path.exists(p) else None

def money(v, dp=0):
    if v is None: return "—"
    return ("−" if v < 0 else "") + (f"${abs(v):,.{dp}f}")

I = {
 "mega": '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
 "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
 "box": '<path d="M12 3 3 7.5v9L12 21l9-4.5v-9z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>',
 "alert": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
 "dollar": '<circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .9 3 2.1-1.3 1.9-3 1.9c-1.4 0-2.5-.5-3-1.5M12 6.5v11"/>',
 "msg": '<path d="M4 5h16v11H9l-5 4z"/>',
 "bag": '<path d="M5 8h14l-1 12H6z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
 "bars": '<path d="M5 20V12M10 20V7M15 20v-5M20 20V4"/>',
 "tag": '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>',
 "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}
def svg(k, cls=""):
    return f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{I[k]}</svg>'
LOOK = {"daily": ("blue", "mega", ["dollar", "msg", "bag", "bars"], ["blue", "purple", "green", "blue"]),
        "monthly": ("green", "trend", [None] * 4, ["green", "blue", "orange", "green"]),
        "stock": ("orange", "box", ["box", "box", "tag"], [])}

def spark(vals, color):
    v = [float(x) for x in (vals or []) if x is not None]
    if len(v) < 2: return ""
    lo, hi = min(v), max(v); rg = (hi - lo) or 1
    pts = " ".join(f"{i / (len(v) - 1) * 100:.1f},{23 - (x - lo) / rg * 20:.1f}" for i, x in enumerate(v))
    return f'<svg class="sp" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true"><polyline style="--lc:var(--{color})" points="{pts}"/></svg>'

def tile(rid, href, title, desc, stats, sparks=None, signal=None, warn="", updated=""):
    c, icon, sicons, lines = LOOK[rid]
    sts = "".join(f'<div class="st" style="--sc:var(--{(lines[i] if i < len(lines) else c)})">{svg(sicons[i], "si") if i < len(sicons) and sicons[i] else ""}'
                  f'<b>{e(str(v))}</b><span>{e(lab)}</span>{spark((sparks or [None] * 4)[i] if sparks and i < len(sparks) else None, lines[i] if i < len(lines) else c)}</div>'
                  for i, (v, lab) in enumerate(stats))
    sig = f'<p class="sig"><span class="pl">{e(signal[0])}</span>{e(signal[1])}</p>' if signal else ""
    wn = f'<span class="wn">{svg("alert")}{e(warn)}</span>' if warn else ""
    return (f'<a class="tile t-{c}" href="{href}"><div class="th"><span class="ic">{svg(icon)}</span><h3>{e(title)}</h3>'
            f'<span class="open" aria-hidden="true">Open <span class="ar">&rsaquo;</span></span><p class="ds">{e(desc)}</p></div>'
            f'<div class="sts n{len(stats)}">{sts}</div>{sig}<div class="ft"><span class="u">{svg("clock")}Updated {e(updated)}</span>{wn}</div></a>')

d, m, k = load("daily"), load("monthly"), load("stock")
tiles = []
if d:
    tiles.append(tile("daily", "daily.html", "Non-tracked campaigns, daily",
        "Spend, messages and cost per message by campaign for today, this week, this month and lifetime, with FB sales, ROAS and orders still to attribute.",
        [(money(d["t_s"], 2), f'spent {d.get("today_date","today")}'), (f'{int(d["t_m"])}', f'msgs {d.get("today_date","today")}'), (money(d["m_sales"]), "FB sales this month"),
         (f'{d["m_roas"]:.2f}x' if d["m_roas"] else "—", "ROAS this month")],
        d.get("spark"), (d["sig_label"], d["reason"]) if d.get("sig") else None,
        f'{d["unatt"]} orders need a source' if d.get("unatt") else "", d["updated"]))
if m:
    tiles.append(tile("monthly", "monthly.html", "Monthly profitability",
        f'Spend, revenue, ROAS and net profit after GST, product cost and ads, month by month from {m["since"]}, with daily detail and a budget signal.',
        [(money(m["np"]), f'net profit, {m["month"]}'), (f'{m["roas"]:.2f}x', "ROAS this month"), (money(m["spend"]), "spend this month"),
         (money(m["total_np"]), f'net profit since {m["since"]}')],
        m.get("spark"), (m["sig_label"], m["reason"]) if m.get("sig") else None, "", m["updated"]))
if k:
    tiles.append(tile("stock", "stock.html", "Shop restock from Backup",
        "Variants with no stock at Shop location that have stock at Backup, with image, product, variant and both stock counts.",
        [(k["variants"], "variants to move"), (k["units"], "units at Backup"), (k["products"], "products")],
        None, None, f'{k["variants"]} variants out of stock at Shop location' if k["variants"] else "", k["updated"]))

upd = (d or m or k or {}).get("updated", "")
CSS = r""":root{
  --bg:#EEF2F9;--card:#FFFFFF;--ink:#0F172A;--muted:#475063;--line:#D9DEE6;--sub:#EEF1F5;
  --navy:#14213D;--mari:#E8A317;--acc:#1D4ED8;--accb:#DCE7FF;
  --g:#17694A;--gb:#D5F2E3;--y:#7A4E00;--yb:#FFEDBF;--r:#A8231B;--rb:#FFE0DC;
  --t:#1D4ED8;--tb:#DCE7FF;--w:#6D28D9;--wb:#ECE3FF;--m:#0F766E;--mb:#D3F2EE;--l:#9A3412;--lb:#FCE6D6;
  --blue:#2563EB;--green:#16A34A;--orange:#EA580C;--purple:#7C3AED;--teal:#0D9488;--rose:#E11D48;--red:#DC2626;
  --alertbg:#FEF2F2;--alertline:#FCA5A5;--alertink:#B91C1C;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  color-scheme:dark;--bg:#070B18;--card:#0E1530;--ink:#EEF2FF;--muted:#A3AEC6;--line:#1E2842;--sub:#131B36;
  --acc:#8FB2FF;--accb:#1A2B52;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17;
  --t:#8FB2FF;--tb:#1A2B52;--w:#C3A6FF;--wb:#2C2150;--m:#5FD4C6;--mb:#123D3A;--l:#FFB085;--lb:#43261A;
  --blue:#3B82F6;--green:#22C55E;--orange:#F97316;--purple:#A78BFA;--teal:#2DD4BF;--rose:#FB7185;--red:#F87171;
  --alertbg:rgba(220,38,38,.14);--alertline:rgba(248,113,113,.45);--alertink:#FCA5A5;}}
:root[data-theme="dark"]{
  color-scheme:dark;--bg:#070B18;--card:#0E1530;--ink:#EEF2FF;--muted:#A3AEC6;--line:#1E2842;--sub:#131B36;
  --acc:#8FB2FF;--accb:#1A2B52;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17;
  --t:#8FB2FF;--tb:#1A2B52;--w:#C3A6FF;--wb:#2C2150;--m:#5FD4C6;--mb:#123D3A;--l:#FFB085;--lb:#43261A;
  --blue:#3B82F6;--green:#22C55E;--orange:#F97316;--purple:#A78BFA;--teal:#2DD4BF;--rose:#FB7185;--red:#F87171;
  --alertbg:rgba(220,38,38,.14);--alertline:rgba(248,113,113,.45);--alertink:#FCA5A5;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.5 Figtree,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a.tile{text-decoration:none}
main{max-width:1132px;margin:0 auto;padding:24px 16px 48px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:20px}
h1{font:800 clamp(26px,4.5vw,32px)/1.15 Figtree,sans-serif;margin:0 0 4px}
header p{margin:0;color:var(--muted)}
.tg{flex:none;font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:8px 14px;cursor:pointer}
.tile:focus-visible,.tg:focus-visible{outline:3px solid var(--blue);outline-offset:3px}
.note{margin:20px 2px 0;color:var(--muted);font-size:13.5px}
/* Tiles: frosted glass, one fixed colour per report */
body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:
  radial-gradient(45% 35% at 8% 10%,rgba(37,99,235,.28),transparent 70%),
  radial-gradient(40% 35% at 95% 40%,rgba(22,163,74,.22),transparent 70%),
  radial-gradient(45% 35% at 15% 90%,rgba(234,88,12,.24),transparent 70%)}
.tiles{display:grid;grid-template-columns:1fr;gap:20px;max-width:1100px}
.tile{--c:var(--blue);position:relative;display:flex;flex-direction:column;gap:14px;padding:18px;text-align:left;cursor:pointer;color:var(--ink);font:inherit;border-radius:22px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--c) 20%,rgba(255,255,255,.62)),color-mix(in srgb,var(--c) 38%,rgba(255,255,255,.42)));
  -webkit-backdrop-filter:blur(18px) saturate(160%);backdrop-filter:blur(18px) saturate(160%);
  border:1px solid rgba(255,255,255,.65);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.8),0 2px 4px rgba(15,23,42,.06),0 18px 40px -14px color-mix(in srgb,var(--c) 60%,transparent),0 30px 60px -30px rgba(15,23,42,.35);
  transition:transform .2s,box-shadow .2s}
.tile::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:linear-gradient(180deg,rgba(255,255,255,.35),rgba(255,255,255,0) 40%)}
.tile>*{position:relative}
@media (hover:hover) and (prefers-reduced-motion:no-preference){.tile:hover{transform:translateY(-3px)}}
.t-blue{--c:var(--blue)}.t-green{--c:var(--green)}.t-orange{--c:var(--orange)}.t-purple{--c:var(--purple)}.t-teal{--c:var(--teal)}.t-rose{--c:var(--rose)}
.th{display:grid;grid-template-columns:auto 1fr auto;gap:4px 14px;align-items:start}
.th .ds{grid-column:2/-1}
.ic{grid-row:span 2;width:46px;height:46px;border-radius:14px;display:grid;place-items:center;color:#fff;background:linear-gradient(145deg,color-mix(in srgb,var(--c) 75%,#fff),var(--c));box-shadow:inset 0 1px 0 rgba(255,255,255,.35),0 8px 18px -6px color-mix(in srgb,var(--c) 75%,transparent)}
.tile.alerted .ic{background:linear-gradient(145deg,#F87171,#DC2626);box-shadow:0 0 0 3px rgba(220,38,38,.25),0 8px 18px -6px rgba(220,38,38,.7)}
.ic svg{width:24px;height:24px}
.tile h3{margin:2px 0 0;font:700 19px/1.25 Figtree,sans-serif;text-wrap:balance}
.tile .ds{margin:0;color:var(--muted);font-size:14px}
.open{display:inline-flex;align-items:center;gap:4px;background:var(--c);color:#fff;font-weight:700;font-size:14px;border-radius:99px;padding:7px 14px;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 6px 14px -4px color-mix(in srgb,var(--c) 75%,transparent)}
.open .ar{font-size:18px;line-height:1}
.sts{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.sts.n3{grid-template-columns:repeat(3,1fr)}.sts.n2{grid-template-columns:repeat(2,1fr)}.sts.n1{grid-template-columns:1fr}
.st{border-radius:14px;padding:10px 12px;color:#fff;background:linear-gradient(145deg,color-mix(in srgb,var(--c) 78%,#fff),var(--c));box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 8px 18px -8px color-mix(in srgb,var(--c) 80%,transparent)}
.st .si{display:block;width:22px;height:22px;margin-bottom:2px}
.st b{display:block;font:800 20px/1.2 Figtree,sans-serif;font-variant-numeric:tabular-nums;white-space:nowrap}
.st span{display:block;font-size:12.5px;line-height:1.3;color:rgba(255,255,255,.9)}
.st .sp{display:block;width:100%;height:26px;margin-top:6px;overflow:visible}
.st .sp polyline{fill:none;stroke:rgba(255,255,255,.9);stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.sig{margin:0;font-size:14px;color:var(--muted)}
.pl{display:inline-block;font-weight:700;font-size:12.5px;border-radius:99px;padding:2px 10px;margin-right:8px;background:var(--c);color:#fff}
.ft{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px 12px;font-size:13px;color:var(--muted)}
.ft .u,.wn{display:inline-flex;align-items:center;gap:6px}
.ft .u svg{width:15px;height:15px}
.wn{border:1px solid var(--alertline);background:var(--alertbg);color:var(--alertink);font-weight:700;border-radius:99px;padding:4px 12px}
.wn svg{width:15px;height:15px}
.alert{display:grid;grid-template-columns:auto 1fr;gap:10px;background:var(--alertbg);border:1px solid var(--alertline);border-radius:14px;padding:12px 14px;color:var(--ink);font-size:13.5px}
.alert svg{width:22px;height:22px;color:var(--red);margin-top:1px}
.alert b{display:block;color:var(--alertink);font-size:14.5px}
@media (max-width:600px){
  .tile{padding:14px;border-radius:18px;gap:12px}.th{gap:4px 10px}.ic{width:40px;height:40px;border-radius:12px;grid-row:auto}.ic svg{width:21px;height:21px}
  .tile h3{font-size:17px}.th .ds{grid-column:1/-1;margin-top:6px;font-size:13.5px}.open{padding:6px 12px;font-size:13px}
  .sts{grid-template-columns:repeat(2,1fr)}
}
:root[data-theme="dark"] body::before{background:radial-gradient(45% 35% at 8% 10%,rgba(59,130,246,.22),transparent 70%),radial-gradient(40% 35% at 95% 40%,rgba(34,197,94,.14),transparent 70%),radial-gradient(45% 35% at 15% 90%,rgba(249,115,22,.16),transparent 70%)}:root[data-theme="dark"] .tile{background:linear-gradient(135deg,color-mix(in srgb,var(--c) 32%,rgba(12,18,40,.72)),color-mix(in srgb,var(--c) 12%,rgba(8,12,28,.78)));border-color:color-mix(in srgb,var(--c) 30%,rgba(255,255,255,.08));box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 2px 4px rgba(0,0,0,.4),0 18px 40px -14px color-mix(in srgb,var(--c) 45%,transparent),0 30px 60px -24px rgba(0,0,0,.8)}:root[data-theme="dark"] .tile::before{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,0) 40%)}:root[data-theme="dark"] .st{color:var(--ink);background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}:root[data-theme="dark"] .st .si{color:var(--sc)}:root[data-theme="dark"] .st span{color:var(--muted)}:root[data-theme="dark"] .st .sp polyline{stroke:var(--lc)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) body::before{background:radial-gradient(45% 35% at 8% 10%,rgba(59,130,246,.22),transparent 70%),radial-gradient(40% 35% at 95% 40%,rgba(34,197,94,.14),transparent 70%),radial-gradient(45% 35% at 15% 90%,rgba(249,115,22,.16),transparent 70%)}:root:not([data-theme="light"]) .tile{background:linear-gradient(135deg,color-mix(in srgb,var(--c) 32%,rgba(12,18,40,.72)),color-mix(in srgb,var(--c) 12%,rgba(8,12,28,.78)));border-color:color-mix(in srgb,var(--c) 30%,rgba(255,255,255,.08));box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 2px 4px rgba(0,0,0,.4),0 18px 40px -14px color-mix(in srgb,var(--c) 45%,transparent),0 30px 60px -24px rgba(0,0,0,.8)}:root:not([data-theme="light"]) .tile::before{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,0) 40%)}:root:not([data-theme="light"]) .st{color:var(--ink);background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}:root:not([data-theme="light"]) .st .si{color:var(--sc)}:root:not([data-theme="light"]) .st span{color:var(--muted)}:root:not([data-theme="light"]) .st .sp polyline{stroke:var(--lc)}}

"""
page = ('<title>Indifeels Reports</title>'
 '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
 '<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
 '<style>' + CSS + '</style><main>'
 f'<header><div><h1>Your reports</h1><p>Key insights from your ads, sales and inventory. Last update {e(upd)}.</p></div>'
 '<button class="tg" id="tg" type="button">Dark mode</button></header>'
 f'<section class="tiles">{"".join(tiles)}</section>'
 '<p class="note">Open a report for the full detail. New reports are added here as tiles, so this one link always has everything.</p></main>'
 """<script>
(function(){var r=document.documentElement,b=document.getElementById('tg');
function cur(){var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
function lab(){b.textContent=cur()==='dark'?'Light mode':'Dark mode'}
try{var s=localStorage.getItem('ntr-theme');if(s)r.setAttribute('data-theme',s)}catch(e){}
lab();b.addEventListener('click',function(){var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{localStorage.setItem('ntr-theme',n)}catch(e){}lab()});})();
</script>""")
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
