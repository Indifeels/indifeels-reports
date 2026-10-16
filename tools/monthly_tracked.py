"""Facebook TRACKED monthly profitability page (same look, structure and signal engine as monthly.py).
Usage: python3 monthly_tracked.py DATA_DIR OUT_HTML      (DATA_DIR holds windsor_01.json from fetch_fb_tracked.py)
Env: REPORT_NOW (ISO), SUMMARY_DIR (writes monthly-tracked.json).
Revenue = Meta pixel purchase value of campaigns with "Tracked" in the name; "clicks" take the place of "messages".
"""
import json, datetime as dt, html, sys, os, calendar as _cal
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Australia/Sydney")
HERE = os.path.dirname(os.path.abspath(__file__))
NOW = dt.datetime.now(TZ)
if os.environ.get("REPORT_NOW"): NOW = dt.datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)
src = open(os.path.join(HERE, "monthly.py")).read()

rows_in = json.load(open(os.path.join(sys.argv[1], "windsor_01.json")))["data"]
def tracked(n):
    n = (n or "").lower().replace("-", " ")
    return "tracked" in n and "non tracked" not in n
spd, msd, mrd, odd_m = {}, {}, {}, {}
for r in rows_in:
    if not tracked(r.get("campaign")): continue
    d = r["date"]
    spd[d] = spd.get(d, 0) + (r.get("spend") or 0)
    msd[d] = msd.get(d, 0) + (r.get("clicks") or 0)
    mrd[d] = mrd.get(d, 0) + (r.get("action_values_purchase") or 0)
    odd_m[d] = odd_m.get(d, 0) + (r.get("actions_purchase") or 0)
# Shopify cross-check: orders whose custom order-source field is "FB Online Orders - WEB"
import glob
SHOP_DIR = sys.argv[3] if len(sys.argv) > 3 else sys.argv[1]
SRC_TAG = "FB Online Orders - WEB"
shd = {}; shn = {}; HAVE_SHOP = False
for _f in sorted(glob.glob(os.path.join(SHOP_DIR, "shopify*"))):
    _x = json.load(open(_f))
    if isinstance(_x, dict) and "result" in _x: _x = _x["result"]
    if isinstance(_x, list) and _x and "text" in _x[0]: _x = json.loads(_x[0]["text"])
    HAVE_SHOP = True
    for _v in _x["data"].values():
        for _n in _v["nodes"]:
            if _n.get("cancelledAt") or (_n.get("m") or {}).get("value") != SRC_TAG: continue
            _d = dt.datetime.fromisoformat(_n["processedAt"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
            shd[_d] = shd.get(_d, 0) + float(_n["t"]["shopMoney"]["amount"]); shn[_d] = shn.get(_d, 0) + 1
shm = {}
for _d, _a in shd.items(): shm[_d[:7]] = shm.get(_d[:7], 0) + _a

HAVE_SHOP = HAVE_SHOP and bool(shd)
BODY = open(os.path.join(HERE, "monthly_tracked_view.py")).read()
views = {}
for _src in (("meta", "shop") if HAVE_SHOP else ("meta",)):
    ns = dict(globals())
    if _src == "meta": ns.update(rvd=mrd, odd=odd_m, SFX="")
    else: ns.update(rvd=shd, odd=shn, SFX="_s")
    exec(BODY, ns); views[_src] = ns
V = views["meta"]
rows, T, RS, PANEL_LABEL, COLS, hdr = V["rows"], V["T"], V["RS"], V["PANEL_LABEL"], V["COLS"], V["hdr"]
months = V["months"]
# data for the comparison line: date -> spend, clicks, Meta orders, Meta sales, Shopify orders, Shopify sales
CMP = {"end": NOW.date().isoformat(), "d": {d: [round(spd.get(d, 0), 2), msd.get(d, 0), odd_m.get(d, 0), round(mrd.get(d, 0), 2), shn.get(d, 0), round(shd.get(d, 0), 2)] for d in sorted(set(spd) | set(shd))}}
hdr = "".join(f"<th>{l}</th>" for _, l, *_ in COLS)

# page chrome: reuse monthly.py's CSS and script verbatim
DK = "--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17;--gd:#6FD6A6;--bd:#FF8C80"
css = src.split("<style>\n", 1)[1].split("</style></head>", 1)[0].replace("{{{DK}}}", "{" + DK + "}").replace("{{", "{").replace("}}", "}")
js = "<script>" + src.split("</main><script>", 1)[1].split("</script></body></html>", 1)[0].replace("{{", "{").replace("}}", "}") + "</script>"

def _view(v, vid, hide, label):
    h = v["hdr"].replace(f"<th>{label}</th>", f'<th class="usd">{label}</th>')
    sig = v["SIGP"]
    if vid == "vs": sig = sig.replace("tracked orders", "Shopify orders").replace("tracked sales", "Shopify sales")
    return f'<div class="view" id="{vid}"{" hidden" if hide else ""}>{sig}<div class="wrap"><table><thead><tr><th>Month</th>{h}</tr></thead><tbody>{v["trs"]}</tbody></table></div></div>'
VIEWS = _view(views["meta"], "vm", False, "Meta tracked sales") + (_view(views["shop"], "vs", True, "Shopify FB web sales") if HAVE_SHOP else "")
FBAR = ('<div class="fbar" role="group" aria-label="Revenue source and comparison period"><span class="fl">Revenue source</span>'
        '<div class="seg"><button type="button" id="sm" aria-pressed="true">Meta reported</button>' + ('<button type="button" id="ss" aria-pressed="false">Shopify attributed</button>' if HAVE_SHOP else '') + '</div>'
        + ('<label class="fl" for="cp">Compare over</label><select id="cp"><option value="y">Yesterday</option><option value="7" selected>7 days</option><option value="15">15 days</option><option value="30">30 days</option><option value="0">Lifetime</option></select><span class="fl">Cards show the difference of Shopify against Meta</span>' if HAVE_SHOP else '')
        + '</div>' + ('<div class="cmp" id="cmp" aria-live="polite"></div>' if HAVE_SHOP else ''))
CSSX = """
.fbar{position:sticky;top:0;z-index:20;box-shadow:0 6px 12px -8px rgba(0,0,0,.35);display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:10px}
.fl{font-size:12.5px;font-weight:600;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:99px;overflow:hidden}
.seg button{font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:0;padding:7px 14px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--mari);color:#101828}
.seg button:focus-visible,.fbar select:focus-visible{outline:2px solid var(--mari);outline-offset:1px}
.fbar select{font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:6px 12px}
.cmp{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:14px}
.cmp>div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.cmp .cl{display:block;font-size:12.5px;color:var(--muted);font-weight:600}
.cmp b{display:block;font:700 20px/1.2 "Bricolage Grotesque",Figtree,sans-serif;font-variant-numeric:tabular-nums;margin:2px 0}
.cmp .cs{display:block;font-size:12px;color:var(--muted)}
.cmp .g b{color:var(--g)}.cmp .y b{color:var(--y)}.cmp .r b{color:var(--r)}
.view[hidden]{display:none}
thead th.usd{color:var(--ink);box-shadow:inset 0 -3px 0 var(--mari)}
"""
CMPJS = """<script>
(function(){var D=%s,sm=document.getElementById('sm'),ss=document.getElementById('ss'),vm=document.getElementById('vm'),vs=document.getElementById('vs'),cp=document.getElementById('cp'),box=document.getElementById('cmp');
function show(m){if(!ss)return;vm.hidden=!m;vs.hidden=m;sm.setAttribute('aria-pressed',m);ss.setAttribute('aria-pressed',!m);try{localStorage.setItem('fmt-src',m?'m':'s')}catch(e){}}
if(sm&&ss){sm.onclick=function(){show(true)};ss.onclick=function(){show(false)};try{if(localStorage.getItem('fmt-src')==='s')show(false)}catch(e){}}
var fb=document.querySelector('.fbar');function stk(){if(fb)document.documentElement.style.setProperty('--stk',(fb.offsetHeight+8)+'px')}stk();addEventListener('resize',stk);
var raf=0;function pin(){raf=0;var s=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--stk'))||0;document.querySelectorAll('.view:not([hidden]) .wrap').forEach(function(w){var ths=w.querySelectorAll('thead th'),h=ths.length?ths[0].offsetHeight:0,d=0;if(w.scrollHeight<=w.clientHeight+1){d=Math.max(0,Math.min(s-w.getBoundingClientRect().top,w.clientHeight-h-14))}ths.forEach(function(t){t.style.transform=d?'translateY('+d+'px)':''})})}
function q(){if(!raf)raf=requestAnimationFrame(pin)}addEventListener('scroll',q,{passive:true});addEventListener('resize',q);document.addEventListener('click',function(){setTimeout(q,60)});setTimeout(pin,0);
function $(v){return(v<0?'-':'')+'$'+Math.abs(Math.round(v)).toLocaleString('en-AU')}
function pc(a,b){return b?(a-b)/Math.abs(b)*100:null}
function pt(v){return v==null?'n/a':(v>=0?'+':'-')+Math.abs(v).toFixed(0)+'%%'}
function run(){if(!box)return;var v=cp.value,end=new Date(D.end+'T00:00:00'),n=v==='y'?1:+v,s=0,c=0,mo=0,mr=0,so=0,sr=0;
for(var k in D.d){var d=new Date(k+'T00:00:00');if(d>end)continue;if(n&&(end-d)/864e5>=n)continue;var x=D.d[k];s+=x[0];c+=x[1];mo+=x[2];mr+=x[3];so+=x[4];sr+=x[5]}
var mA=mo?mr/mo:0,sA=so?sr/so:0,mRo=s?mr/s:0,sRo=s?sr/s:0,mP=mr/1.1*.75-s,sP=sr/1.1*.75-s,att=(mr||sr)?Math.min(mr,sr)/Math.max(mr,sr)*100:null,ac=att==null?'':att>=90?'g':att>=70?'y':'r';
function card(l,mv,sv,d,cls){return '<div class="'+(cls||'')+'"><span class="cl">'+l+'</span><b>'+d+'</b><span class="cs">Meta '+mv+' · Shopify '+sv+'</span></div>'}
box.innerHTML=card('Order value',$(mA),$(sA),pt(pc(sA,mA)))+card('Number of orders',mo,so,pt(pc(so,mo)))+card('Sales',$(mr),$(sr),pt(pc(sr,mr)))+card('ROAS',mRo.toFixed(2)+'x',sRo.toFixed(2)+'x',pt(pc(sRo,mRo)))+card('Net profit',$(mP),$(sP),($(sP-mP)))+
'<div class="'+ac+'"><span class="cl">Attribution</span><b>'+(att==null?'n/a':att.toFixed(0)+'%%')+'</b><span class="cs">sales both sources agree on</span></div>'}
if(cp){cp.onchange=run;run()}})();
</script>"""
CMPJS = CMPJS % json.dumps(CMP)
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Facebook tracked monthly profitability</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{css}
{CSSX}
</style></head><body><main>
<header><div class="hd"><h1>Facebook tracked monthly profitability</h1><p>Tracked Meta sales campaigns against the sales Meta tracks to them. Data to {NOW.strftime("%-d %b %Y")}.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
{FBAR}
<div class="bar"><button type="button" id="all">Expand all</button><button type="button" id="none">Collapse all</button></div>
{VIEWS}
<section class="notes">
<div class="box"><h2>How it's calculated</h2>
<p><b style="color:var(--ink)">Shopify FB web sales and Attribution %:</b> a cross-check on Meta's number. Shopify FB web sales is the order total of Shopify orders whose order source field is "FB Online Orders - WEB" (cancelled orders excluded), by the day the order was processed. Attribution % is how much of the money both sources agree on: the smaller of the two figures divided by the larger. Green at 90% or more, yellow 70% to 90%, red under 70%. Profit, ROAS and the signal still use Meta's number.</p>
<p><b style="color:var(--ink)">Meta tracked sales:</b> purchase value Meta records against campaigns with "Tracked" in the name (Non Tracked campaigns are excluded), including GST.</p>
<p><b style="color:var(--ink)">Net profit:</b> tracked sales − GST (1/11 of sales) − product cost (a quarter of sales after GST) − ad spend.</p>
<p><b style="color:var(--ink)">Weekly and daily rows:</b> click a month to see its weeks (Monday to Sunday), then a week to see each day. Daily net profit is green at $33 or more (a monthly $1,000 spread over 30 days), yellow from $0 to $33, red for a loss.</p>
<p><b style="color:var(--ink)">Break-even per click:</b> sales per click × 0.68 (what's left after GST and product cost). A guardrail, not the decision.</p>
<p><b style="color:var(--ink)">Signal:</b> same rules as the non-tracked report, with clicks in place of messages. It compares the last 14 full days with the 14 before (7-day and 28-day windows as checks) and asks whether extra ad spend is still adding profit. Scale Up when each extra $1 returns $1.20 or more of contribution and profit is positive; Hold between $0.90 and $1.20 or when there are under 6 tracked orders; Scale Down under $0.90, or when cost per click is above break-even and the period is making a loss. Click a signal to see why.</p>
<p><b style="color:var(--ink)">Arrows:</b> change on the previous month. Green is better, red is worse, grey is spend.</p>
<p>Starts March 2026. * Month to date. Meta's own purchase tracking can differ from Shopify orders; see Attribution %.</p></div>
<div class="box"><h2>Colour bands</h2><table>
<tr><th></th><th><span class="v g"><span class="d"></span>Green</span></th><th><span class="v y"><span class="d"></span>Yellow</span></th><th><span class="v r"><span class="d"></span>Red</span></th></tr>
<tr><td>ROAS</td><td>2.0x or more</td><td>1.47x to 2.0x</td><td>under 1.47x (loss)</td></tr>
<tr><td>Cost per click</td><td>under $0.40</td><td>$0.40 to $0.60</td><td>over $0.60</td></tr>
<tr><td>Sales per click</td><td>$1.20 or more</td><td>$0.80 to $1.20</td><td>under $0.80</td></tr>
<tr><td>Clicks to orders</td><td>2% or more</td><td>1% to 2%</td><td>under 1%</td></tr>
<tr><td>Attribution %</td><td>90% or more</td><td>70% to 90%</td><td>under 70%</td></tr>
<tr><td>Net profit</td><td>$1,000 or more</td><td>$0 to $1,000</td><td>loss</td></tr>
<tr><td>Net profit per click</td><td>$0.30 or more</td><td>$0 to $0.30</td><td>loss</td></tr>
</table></div></section>
</main>{js}{CMPJS}</body></html>'''
sys.path.insert(0, HERE)
import tile_periods as _tp
page = page.replace("</body>", _tp.tag(_tp.periods(NOW.date(), spd, mrd)) + "</body>", 1)
open(sys.argv[2], "w").write(page)
if os.environ.get("SUMMARY_DIR"):
    _cm = rows[-1][1]
    _cum = []; _c = 0
    for _n, _d in rows: _c += _d["np"]; _cum.append(round(_c, 2))
    SPARK = [[round(d["np"], 2) for _, d in rows], [round(d["roas"] or 0, 2) for _, d in rows], [round(d["s"], 2) for _, d in rows], _cum]
    json.dump(dict(spark=SPARK, updated=NOW.strftime("%-d %b %Y, %-I:%M %p"), month=rows[-1][0].rstrip("*"), np=_cm["np"], roas=_cm["roas"], rev=_cm["r"], spend=_cm["s"],
                   total_np=T["np"], since=dt.date.fromisoformat(months[0] + "-01").strftime("%b %Y"),
                   sig=RS["code"], sig_label=PANEL_LABEL, reason=RS["reason"]), open(os.path.join(os.environ["SUMMARY_DIR"], "monthly-tracked.json"), "w"))
for n, d in rows: print(n, d["sig"]["label"], "|", d["sig"]["reason"][:100])
