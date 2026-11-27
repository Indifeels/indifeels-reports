"""Build the encrypted SEO Final report (admin-only, category SEO).
Usage: python3 tools/seo_final.py DATA.json [--html OUT.html]
Env: SEO_FINAL_KEY (base64 AES-256 key from Supabase report_keys, report_id='seo-final')
DATA.json is NOT stored in this public repo (see seo_final_REFRESH.md).
"""
import json,html,sys,os,gzip,base64,subprocess
D=json.load(open(sys.argv[1]))
R=D['R'];KD=D['KD'];KW=D['KW'];rows=D['rows'];pr=[tuple(x) for x in D['pr']];colfill=D['col'];have=D['have'];tgt=D['tgt']
def k(n): return f"{n/1000:.1f}K" if n>=1000 else str(n)
mx=max(R[r[1]]['vol'] for r in rows)
cards=''
for lab,c,s,col in rows:
    r=R[c];vol=r['vol'];kd=KD[c]
    kdc='#2e7d32' if kd<20 else '#f9a825' if kd<30 else '#c62828'
    spp=vol/s if s else None
    if s is None: g,gc,gt='–','#9e9e9e','in Suits'
    elif s==0: g,gc,gt='🚫','#c62828','NO STOCK'
    elif spp>600: gc,gt='#c62828','BIG GAP'
    elif spp>250: gc,gt='#f9a825','GAP'
    else: gc,gt='#2e7d32','OK'
    stock_w=min((s or 0)/200*100,100)
    rk=round(r['ranked']/r['kw']*100)
    chips=''.join(f'<div class="kl {"g" if 0<p<=10 else "a" if p>10 else "r"}"><span class=kn>{w}</span><span>{k(v)}</span><span class=kdd style="background:{"#2e7d32" if (d or 0)<20 else "#f9a825" if (d or 0)<30 else "#c62828"}">{d if d is not None else "–"}</span><span class=kp>{("#"+str(p)) if p else "—"}</span></div>' for w,v,p,d in KW[c])
    cards+=f'''<div class=wrap><div class=row style="--c:{col}"><div class=nm>{lab}</div>
<div class=bars><div class=bd><u style="width:{vol/mx*100:.0f}%"></u><span>{k(vol)}</span></div>
<div class=bs><u style="width:{stock_w:.0f}%"></u><span>{'' if s is None else s}</span></div></div>
<div class=dots><span class=kd style="background:{kdc}">{kd:.0f}</span><span class=rk style="--p:{rk}"><b>{rk}%</b></span></div>
<div class=gap style="background:{gc}">{gt}</div></div><details class=kws><summary>Keywords</summary><div class=klh><span></span><span>Searches</span><span>Diff.</span><span>Our rank</span></div>{chips}</details></div>'''

pmax=420
ph=''
for n,o,cs,adv in pr:
    bars=f'<div class=pb><u style="width:{o/pmax*100:.0f}%;background:#e91e63"></u><span>You ${o}</span></div>'
    for a,v in cs: bars+=f'<div class=pb><u style="width:{v/pmax*100:.0f}%;background:#90a4ae"></u><span>{a} ${v}</span></div>'
    ph+=f'<div class=prow><div class=nm2>{n}</div><div>{bars}</div><div class=adv>${adv.replace("hold ","")}</div></div>'
cf=''.join(f'<div class=cf><span>{n}</span><div class=cb><u style="width:{p}%;background:{"#e53935" if p<60 else "#fb8c00" if p<85 else "#2e7d32"}"></u></div><b>{p}%</b></div>' for n,p in colfill)

sizes=['32','34','36','38','40','42','44','46','48','50','52','54']
def cc(p):
    return '#2e7d32' if p>=1 else '#7cb342' if p>=.75 else '#fdd835' if p>=.5 else '#fb8c00' if p>=.25 else '#e53935'
hm='<div class=hm><div class=hl></div>'+''.join(f'<div class=hh>{s}</div>' for s in sizes)
hm+='<div class=hl>Target</div>'+''.join(f'<div class="hh t">{t}</div>' for t in tgt)
for n,h in have.items():
    pct=round(sum(min(a,t) for a,t in zip(h,tgt))/sum(tgt)*100)
    hm+=f'<div class=hl>{n}<b>{pct}%</b></div>'
    for a,t in zip(h,tgt):
        p=a/t;hm+=f'<div class=hc style="background:{cc(p)};color:{"#222" if .25<=p<.75 else "#fff"}">{a}</div>'
hm+='</div>'
page=f'''<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>SEO Final</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#121417;color:#ecebe6;font:13px/1.3 system-ui,sans-serif;padding:12px;max-width:520px;margin:auto}}
h1{{font-size:22px;margin:4px 0 2px}}.sub{{color:#8f959d;font-size:11px}}h2{{font-size:15px;margin:20px 0 8px}}
.leg{{display:flex;gap:10px;flex-wrap:wrap;font-size:10.5px;margin:4px 0 8px;color:#a3a9b1}}.leg i{{display:inline-block;width:10px;height:10px;border-radius:3px;vertical-align:-1px;margin-right:3px}}
.row{{background:#1d2025;border-radius:14px;padding:9px 10px;margin:7px 0;display:grid;grid-template-columns:78px 1fr 62px 66px;gap:8px;align-items:center;box-shadow:0 1px 4px #0006;border-left:6px solid var(--c)}}
.nm{{font-weight:700;font-size:12.5px;color:var(--c)}}.bars>div{{height:15px;border-radius:8px;background:#2c3036;position:relative;margin:2px 0;overflow:hidden}}
.bars u{{display:block;height:100%;border-radius:8px}}.bd u{{background:var(--c)}}.bs u{{background:#78909c}}.bars span{{position:absolute;right:7px;top:0;font-size:10px;font-weight:700;color:#fff;line-height:15px;text-shadow:0 0 3px #000}}
.dots{{display:flex;gap:5px;align-items:center}}.kd{{color:#fff;font-weight:700;border-radius:8px;padding:3px 6px;font-size:11px}}
.rk{{width:30px;height:30px;border-radius:50%;background:conic-gradient(#1e88e5 calc(var(--p)*1%),#2c3036 0);display:grid;place-items:center;position:relative}}.rk b{{background:#1d2025;color:#ecebe6;border-radius:50%;width:22px;height:22px;display:grid;place-items:center;font-size:8px}}
.gap{{color:#fff;font-weight:800;font-size:10px;text-align:center;border-radius:9px;padding:6px 2px}}
.hm{{display:grid;grid-template-columns:70px repeat(12,1fr);gap:2px;font-size:10px}}.hl{{display:flex;flex-direction:column;justify-content:center;font-weight:700;font-size:10.5px}}.hl b{{font-size:9px;color:#8f959d}}
.hh{{text-align:center;font-weight:700;color:#a3a9b1}}.hh.t{{color:#64b5f6}}.hc{{text-align:center;padding:7px 0;border-radius:5px;font-weight:700}}
.ask{{display:grid;gap:6px;margin-top:6px}}.ask div{{background:#1d2025;border-radius:12px;padding:9px 11px;border-left:5px solid #ff6f00;font-size:12.5px}}.ask b{{color:#ff6f00}}
.prow{{display:grid;grid-template-columns:62px 1fr 54px;gap:8px;align-items:center;background:#1d2025;border-radius:12px;padding:8px 10px;margin:6px 0}}.nm2{{font-weight:700;font-size:12px}}.pb{{height:13px;background:#2c3036;border-radius:7px;margin:2px 0;position:relative;overflow:hidden}}.pb u{{display:block;height:100%;border-radius:7px}}.pb span{{position:absolute;left:6px;top:0;font-size:9.5px;font-weight:700;line-height:13px;color:#fff;text-shadow:0 0 3px #0009}}.adv{{background:#2e7d32;color:#fff;font-weight:800;font-size:11px;text-align:center;border-radius:8px;padding:5px 0}}.cf{{display:grid;grid-template-columns:62px 1fr 36px;gap:8px;align-items:center;margin:6px 0;font-weight:700;font-size:12px}}.cb{{height:12px;background:#2c3036;border-radius:7px;overflow:hidden}}.cb u{{display:block;height:100%}}.tag{{display:inline-block;background:#1e2a3d;color:#64b5f6;border-radius:8px;padding:2px 7px;font-size:10.5px;margin-right:4px}}
.wrap{{margin:7px 0}}.wrap .row{{margin:0;border-radius:14px 14px 0 0}}.kws{{background:#1d2025;border-radius:0 0 14px 14px;padding:0 10px 8px;border-left:6px solid transparent}}.kws summary{{display:block;cursor:pointer;font-size:11px;color:#8f959d;padding:2px 0 4px;list-style:none}}.kws summary::before{{content:'▸ '}}.kws[open] summary::before{{content:'▾ '}}.kl,.klh{{display:grid;grid-template-columns:1fr 46px 34px 46px;gap:6px;align-items:center;margin:3px 0;font-size:11px;text-align:right}}.klh{{color:#8f959d;font-size:9.5px}}.kn{{text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.kdd{{color:#fff;font-weight:700;border-radius:7px;padding:1px 0;text-align:center}}.kl.g .kp{{color:#66bb6a;font-weight:700}}.kl.a .kp{{color:#ffb74d;font-weight:700}}.kl.r .kp{{color:#ef5350}}.kc{{font-size:10px;padding:3px 7px;border-radius:9px;color:#fff}}.kc b{{opacity:.85;margin-left:2px}}.kc.g{{background:#2e7d32}}.kc.a{{background:#b7791f}}.kc.r{{background:#8e2b2b}}</style></head><body>
<h1>SEO Final</h1><div class=sub>Australia only · searches {D['meta']['searches_date']} · stock {D['meta']['stock_date']}</div>
<h2>Demand vs stock</h2>
<div class=leg><span><i style="background:#e91e63"></i>Searches / month</span><span><i style="background:#78909c"></i>Products in stock</span><span><i style="background:#2e7d32"></i>Easy</span><span><i style="background:#f9a825"></i>Medium</span><span><i style="background:#c62828"></i>Hard</span><span><i style="background:#1e88e5"></i>% keywords we rank</span><span>Tap “Keywords” to open</span></div>
{cards}
<h2>Sizes: stock vs target</h2>
<div class=leg><span><i style="background:#2e7d32"></i>Full</span><span><i style="background:#7cb342"></i>75%+</span><span><i style="background:#fdd835"></i>50%+</span><span><i style="background:#fb8c00"></i>25%+</span><span><i style="background:#e53935"></i>Under 25%</span></div>
{hm}
<h2>Colours filled in (in-stock products)</h2><div class=sub>Colour field is empty on many products, so a colour gap view isn't reliable yet</div>{cf}
<h2>Price vs AU competitors</h2><div class=sub>Median price · HoN House of Nepal · TDO Designer Outfit · Fab Fabricoz · right = suggested</div>{ph}
</body></html>'''

# Preserve the private tracker on ordinary report rebuilds. Explicit data wins.
from seo_change_tracker import inject as inject_tracker, BEGIN as TRACKER_BEGIN, END as TRACKER_END
tracker_path=os.environ.get('SEO_CHANGE_TRACKER_DATA')
if tracker_path:
    page=inject_tracker(page,json.load(open(tracker_path)))
elif os.environ.get('SEO_FINAL_KEY'):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from pathlib import Path
    existing=Path(__file__).resolve().parent.parent/'r'/'seo-final.bin'
    if existing.exists():
        old=existing.read_bytes()
        old_page=gzip.decompress(AESGCM(base64.b64decode(os.environ['SEO_FINAL_KEY'])).decrypt(old[:12],old[12:],None)).decode()
        if TRACKER_BEGIN in old_page:
            import re
            match=re.search(re.escape(TRACKER_BEGIN)+r'.*?'+re.escape(TRACKER_END),old_page,re.S)
            if not match: raise ValueError('Incomplete saved SEO tracker')
            page=page.replace('</body>',match.group(0)+'\n</body>')

if '--html' in sys.argv:
    open(sys.argv[sys.argv.index('--html')+1],'w').write(page);sys.exit(0)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key=base64.b64decode(os.environ.get('SEO_FINAL_KEY',''))
if len(key)!=32: sys.exit('SEO_FINAL_KEY missing or not 32 bytes')
def enc(b):
    iv=os.urandom(12);return iv+AESGCM(key).encrypt(iv,gzip.compress(b,9),None)
RD=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','r')
import datetime
now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=11)))
big=sorted(R[c]['vol']/s for _,c,s,_ in rows if s)
top=max(((R[c]['vol']/s,l) for l,c,s,_ in rows if s),default=(0,''))
meta=dict(updated=now.strftime('%d %b %Y, %H:%M'),stats=[[k(R['Sarees']['vol']),'sarees searches / month'],[str(sum(1 for _,c,s,_ in rows if s==0)),'categories with no stock'],[str(len(rows)),'categories tracked']],
 signal=dict(code='hold',label='GAPS',reason='Biggest gap: '+top[1]+' ('+k(round(top[0]))+' searches per product).'),warn='')
open(os.path.join(RD,'seo-final.bin'),'wb').write(enc(page.encode()))
open(os.path.join(RD,'seo-final.meta.bin'),'wb').write(enc(json.dumps(meta).encode()))
subprocess.run([sys.executable,os.path.join(os.path.dirname(os.path.abspath(__file__)),'status.py'),RD,'seo-final','ok'],check=True)
print('wrote r/seo-final.bin, r/seo-final.meta.bin')
