"""Build the encrypted SEO Intelligence report (admin-only, category SEO).
Usage: python3 tools/seo_progress.py DATA.json [--html OUT.html]
Env: SEO_INTELLIGENCE_KEY (base64 AES-256 key, Supabase report_keys, report_id='seo-intelligence')
DATA.json is NOT stored in this public repo.
"""
import json,sys,os,gzip,base64,subprocess,datetime,html
D=json.load(open(sys.argv[1]))
def bars(rows,col):
    m=max(v for _,v,*_ in rows) or 1
    return ''.join(f'<div class=br><span class=bl>{html.escape(l)}</span><div class=bt><u style="width:{v/m*100:.0f}%;background:{col}"></u></div><b>{v:,}</b></div>' for l,v,*_ in rows)
def tiles(ts):
    return '<div class=tl>'+''.join(f'<div class=t style="--c:{c}"><b>{html.escape(str(n))}</b><span>{html.escape(l)}</span></div>' for n,l,c in ts)+'</div>'
def chips(items):
    return ''.join(f'<div class=ch><b>{html.escape(a)}</b><span>{html.escape(b)}</span></div>' for a,b in items)
sem=[(l,k) for l,k,_ in D['semrush']];gsc=[(l,k) for l,k in D['gsc']]
gap=''.join(f'<div class=row style="--c:{c}"><div class=nm>{html.escape(n)}</div><div class=g2><span>{html.escape(a)}</span><span>{html.escape(b)}</span></div><div class=st style="background:{c}">{html.escape(s)}</div></div>' for n,a,b,s,c in D['gap'])
audit=''.join(f'<div class=br><span class=bl>{html.escape(l)}</span><div class=bt><u style="width:{min(v/D["audit_max"]*100,100):.0f}%;background:#fb8c00"></u></div><b>{v:,}</b></div>' for l,v in D['audit'])
pilot=''.join(f'<div class=pl><a href="https://indifeels.com/products/{h}" target=_blank rel=noopener>{html.escape(t)}</a><span>{html.escape(n)}</span></div>' for h,t,n in D['pilot'])
nxt=''.join(f'<div class=ask><b>{html.escape(a)}</b> {html.escape(b)}</div>' for a,b in D['next'])
mon=''.join(f'<div class=pl><span>{html.escape(a)}</span><span>{html.escape(b)}</span></div>' for a,b in D['monitor'])
page=f'''<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>SEO Intelligence</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#121417;color:#ecebe6;font:13px/1.35 system-ui,sans-serif;padding:12px;max-width:520px;margin:auto}}
h1{{font-size:22px;margin:4px 0 2px}}.sub{{color:#8f959d;font-size:11px}}h2{{font-size:15px;margin:20px 0 8px}}
.tl{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.t{{background:#1d2025;border-radius:14px;padding:10px 12px;border-left:6px solid var(--c)}}.t b{{display:block;font-size:24px;color:var(--c)}}.t span{{font-size:11px;color:#a3a9b1}}
.br{{display:grid;grid-template-columns:78px 1fr 52px;gap:8px;align-items:center;margin:5px 0;font-size:11.5px}}.bt{{height:15px;background:#2c3036;border-radius:8px;overflow:hidden}}.bt u{{display:block;height:100%;border-radius:8px}}.br b{{text-align:right}}
.row{{background:#1d2025;border-radius:12px;padding:9px 10px;margin:6px 0;display:grid;grid-template-columns:74px 1fr 66px;gap:8px;align-items:center;border-left:6px solid var(--c)}}.nm{{font-weight:700;color:var(--c)}}.g2 span{{display:block;font-size:11px;color:#c7ccd2}}.st{{color:#fff;font-weight:800;font-size:10px;text-align:center;border-radius:9px;padding:6px 2px}}
.pl{{background:#1d2025;border-radius:10px;padding:7px 10px;margin:4px 0;display:flex;justify-content:space-between;gap:8px;font-size:11.5px}}.pl a{{color:#64b5f6;text-decoration:none}}.pl span{{color:#a3a9b1;text-align:right}}
.ask{{background:#1d2025;border-radius:12px;padding:9px 11px;margin:6px 0;border-left:5px solid #ff6f00;font-size:12.5px}}.ask b{{color:#ff6f00}}
.ch{{display:inline-block;background:#1d2025;border-radius:10px;padding:5px 9px;margin:3px 3px 0 0;font-size:11px}}.ch b{{margin-right:5px}}.note{{color:#8f959d;font-size:11px;margin:4px 0}}
</style></head><body><h1>SEO Intelligence</h1><div class=sub>Australia only · Semrush as of {D['dates']['semrush']} · Search Console as of {D['dates']['gsc']} · updated {D['dates']['built']}</div>
<h2>Where we stand</h2>{tiles(D['tiles'])}
<h2>Semrush organic rank (keywords)</h2>{bars([(l,k) for l,k,_ in D['semrush']],'#1e88e5')}
<div class=note>Semrush and Search Console are measured differently. Never compare them directly.</div>
<h2>Search Console, last 90 days (avg position)</h2>{bars(gsc,'#8e24aa')}
<h2>Position Tracking: AI Overview vs organic</h2>{tiles(D['track'])}<div class=note>Most "rank 1" results are Google's AI box citing us, not the #1 blue link.</div>
<h2>Protected pages</h2>{tiles(D['prot'])}
<h2>Search demand vs stock (we rank nowhere)</h2>{gap}
<h2>Pilot: sarees updated {D['dates']['pilot']}</h2>{tiles(D['pilot_tiles'])}<div class=note>Additions only. Facts (fabric, work) unchanged. Old text saved for rollback.</div>{pilot}
<h2>Tracking the pilot</h2>{mon}
<h2>Site Audit (Semrush)</h2>{audit}
<h2>Next</h2>{nxt}
</body></html>'''
if '--html' in sys.argv:
    open(sys.argv[sys.argv.index('--html')+1],'w').write(page);sys.exit(0)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key=base64.b64decode(os.environ.get('SEO_INTELLIGENCE_KEY',''))
if len(key)!=32: sys.exit('SEO_INTELLIGENCE_KEY missing or not 32 bytes')
def enc(b):
    iv=os.urandom(12);return iv+AESGCM(key).encrypt(iv,gzip.compress(b,9),None)
RD=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','r')
now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=11)))
meta=dict(updated=now.strftime('%d %b %Y, %H:%M'),stats=D['meta_stats'],signal=dict(code='hold',label=D['meta_label'],reason=D['meta_reason']),warn='')
open(os.path.join(RD,'seo-intelligence.bin'),'wb').write(enc(page.encode()))
open(os.path.join(RD,'seo-intelligence.meta.bin'),'wb').write(enc(json.dumps(meta).encode()))
subprocess.run([sys.executable,os.path.join(os.path.dirname(os.path.abspath(__file__)),'status.py'),RD,'seo-intelligence','ok'],check=True)
print('wrote r/seo-intelligence.bin, r/seo-intelligence.meta.bin')
