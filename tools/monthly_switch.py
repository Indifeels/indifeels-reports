"""Wrap the tracked and non-tracked monthly pages in one Facebook Monthly Profitability page with a switch.
Usage: python3 monthly_switch.py TRACKED_HTML NONTRACKED_HTML OUT_HTML"""
import sys, html, re, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
import tile_periods as tp
t, n = (open(p).read() for p in sys.argv[1:3])
fr = lambda i, h, hid: f'<iframe id="{i}" title="{i}" {"hidden " if hid else ""}srcdoc="{html.escape(h, quote=True)}"></iframe>'
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Facebook monthly profitability</title>
<style>
:root{{--bg:#F6F7F9;--card:#FFF;--ink:#101828;--line:#D9DEE6;--mari:#E8A317}}
:root[data-theme="dark"]{{--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--line:#2A303B}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--line:#2A303B}}}}
html,body{{margin:0;height:100%;background:var(--bg);font:600 14px Figtree,system-ui,sans-serif;color:var(--ink)}}
nav{{display:flex;gap:8px;padding:12px 16px 0;max-width:1500px;margin:0 auto}}
nav button{{font:600 14px Figtree,system-ui,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:8px 18px;cursor:pointer}}
nav button[aria-pressed="true"]{{background:var(--mari);border-color:var(--mari);color:#101828}}
nav button:focus-visible{{outline:2px solid var(--mari);outline-offset:2px}}
iframe{{display:block;border:0;width:100%;height:calc(100% - 56px)}}iframe[hidden]{{display:none}}
</style></head><body>
<nav role="group" aria-label="Campaign type"><button type="button" id="bt" aria-pressed="true">Facebook Tracked</button><button type="button" id="bn" aria-pressed="false">Facebook Non-tracked</button></nav>
{fr("ft", t, False)}{fr("fn", n, True)}
<script>
(function(){{var T=document.getElementById('ft'),N=document.getElementById('fn'),bt=document.getElementById('bt'),bn=document.getElementById('bn');
function show(t){{T.hidden=!t;N.hidden=t;bt.setAttribute('aria-pressed',t);bn.setAttribute('aria-pressed',!t);try{{localStorage.setItem('fm-tab',t?'t':'n')}}catch(e){{}}}}
bt.onclick=function(){{show(true)}};bn.onclick=function(){{show(false)}};
try{{if(localStorage.getItem('fm-tab')==='n')show(false)}}catch(e){{}}
function theme(){{try{{return localStorage.getItem('ntr-theme')}}catch(e){{return null}}}}
function sync(f){{f.addEventListener('load',function(){{var d=f.contentDocument;if(!d)return;var th=theme();if(th){{d.documentElement.setAttribute('data-theme',th);document.documentElement.setAttribute('data-theme',th)}}
var b=d.getElementById('tg');if(b)b.addEventListener('click',function(){{var th=d.documentElement.getAttribute('data-theme');document.documentElement.setAttribute('data-theme',th);[T,N].forEach(function(o){{if(o!==f&&o.contentDocument)o.contentDocument.documentElement.setAttribute('data-theme',th)}})}})}})}}
sync(T);sync(N);}})();
</script></body></html>'''
def g(h):
    m = re.search(r'<script type="application/json" id="tile-periods">(.*?)</script>', h, re.S)
    return json.loads(m.group(1)) if m else None
blocks = [b for b in (g(t), g(n)) if b]
if blocks: page = page.replace("</body>", tp.tag(tp.sums(*blocks)) + "</body>", 1)
open(sys.argv[3], "w").write(page)
