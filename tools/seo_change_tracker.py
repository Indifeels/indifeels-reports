"""Render/publish private SEO tracking data inside the encrypted SEO Final report.
Usage: SEO_FINAL_KEY=... python3 tools/seo_change_tracker.py PRIVATE.json [--html PREVIEW]
No plaintext data belongs in this public repository.
"""
import argparse,base64,datetime,gzip,html,json,os,re
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
BEGIN='<!-- SEO_CHANGE_TRACKER_START -->'
END='<!-- SEO_CHANGE_TRACKER_END -->'
def esc(v): return html.escape(str(v if v is not None else 'Unknown'),quote=True)
def num(v): return '—' if v is None else f'{v:,}'
def metrics(m):
    if m is None: return 'Awaiting complete post-change data'
    return f"{num(m['clicks'])} clicks · {num(m['impressions'])} impressions · CTR {esc(m['ctr'])}% · avg position {esc(m['position'])}"
def render(d):
    dates=d['schedule']['dates']; active=d['schedule'].get('active',False)
    out=[BEGIN,'''<section id="seo-change-tracker" aria-label="SEO change tracker"><style>
#seo-change-tracker{margin-top:24px;border-top:1px solid #40444d;padding-top:12px}#seo-change-tracker .ct-card{background:#1d2025;border:1px solid #343941;border-radius:12px;margin:12px 0;padding:12px}#seo-change-tracker h3{margin:0 0 8px;font-size:16px;color:#cebcf3}#seo-change-tracker p{line-height:1.55}#seo-change-tracker .ct-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}#seo-change-tracker .ct-grid div{background:#292d34;border-radius:8px;padding:8px}#seo-change-tracker .ct-grid b{font-size:20px;display:block}#seo-change-tracker .ct-grid span{font-size:10px;color:#bbc1ca}#seo-change-tracker .ct-note{font-size:11px;color:#aeb5bf;line-height:1.5}#seo-change-tracker summary{cursor:pointer;padding:9px 0;color:#bca5eb}#seo-change-tracker a{color:#8ecbff}#seo-change-tracker .ct-product{border-top:1px solid #3b4049;padding:10px 0;overflow-wrap:anywhere}#seo-change-tracker .ct-period{border-left:3px solid #bca5eb;padding-left:8px;margin:10px 0}#seo-change-tracker .ct-scroll{overflow-x:auto}#seo-change-tracker table{border-collapse:collapse;font-size:11px;width:100%;min-width:570px}#seo-change-tracker td,#seo-change-tracker th{text-align:left;padding:8px;border-bottom:1px solid #41454d}#seo-change-tracker th{color:#cebcf3}#seo-change-tracker .ct-chip{display:inline-block;background:#2b3545;color:#a7d4ff;border-radius:5px;padding:4px 6px;margin:3px}#seo-change-tracker .ct-copy{white-space:pre-wrap;font-size:11px;background:#15171b;padding:7px;border-radius:6px}
</style><h2>SEO change tracker</h2>''',f'<p class="ct-note">Updated {esc(d["asOf"])} · catalogue {esc(d["catalogueAsOf"])} · {len(d["categories"])} existing categories</p>',f'<p><b>Performance reviews: {"Scheduled" if active else "Not scheduled"}</b><br>'+ ' · '.join(esc(x) for x in dates) + '<br><span class="ct-note">Melbourne morning, approximately 8 am. Weekly, with a final check to allow for reporting delay. Data availability can delay a completed review.</span></p>', '<div class="ct-scroll"><table><thead><tr><th>Category</th><th>Products</th><th>In stock</th><th>Updated</th><th>Pending review</th><th>Protected</th><th>Unavailable</th></tr></thead><tbody>']
    for idx,c in enumerate(d['categories']):
        out.append(f'<tr><td><a href="#ct-{idx}">{esc(c["label"])}</a></td>'+''.join(f'<td>{c[k]}</td>' for k in ['total','inStock','published','pending','protected','excluded'])+'</tr>')
    out+=['</tbody></table></div><p class="ct-note">Updated = recorded published edits. Pending review = available, unprotected products with no recorded edit; eligibility and keyword research still need checking. Categories overlap; do not add totals together.</p>']
    for idx,c in enumerate(d['categories']):
        out += [f'<details class="ct-card" id="ct-{idx}"><summary><b>{esc(c["label"])}</b> · {c["published"]} updated / {c["total"]} products</summary><div class="ct-grid">']
        for key,label in [('total','Products'),('inStock','In stock'),('published','Published edits'),('pending','Pending review'),('protected','Protected in stock'),('excluded','Unavailable / inactive')]:
            out.append(f'<div><b>{c[key]}</b><span>{label}</span></div>')
        out += [f'</div><p class="ct-note">{c["metadataOnly"]} metadata-only edits; {c["published"]-c["metadataOnly"]} with other content edits. A published metadata or content change does not establish full optimisation. Unavailable products can include previously edited pages.</p>',f'<div class="ct-period"><b>Previous: {esc(" to ".join(d["periods"]["previous"]))}</b><p>{metrics(c["previous"])}</p></div>',f'<div class="ct-period"><b>Before changes: {esc(" to ".join(d["periods"]["baseline"]))}</b><p>{metrics(c["baseline"])}</p><span class="ct-note">Changed products only: {metrics(c["changedBaseline"])}</span></div>',f'<div class="ct-period"><b>After changes</b><p>{metrics(c.get("after"))}</p>'+ (f'<span class="ct-note">Window: {esc(c["after"].get("start"))} to {esc(c["after"].get("end"))}<br>Changed products only: {metrics(c["after"].get("changedProducts"))}</span>' if c.get('after') else '')+'</div>',f'<p class="ct-note">Next check: {esc(c.get("nextCheck",dates[0]))}. Review at 7, 14 and 28 days from each publication, using complete comparable windows. These are early signals, not proof of SEO impact.</p>']
        if c.get('details'):
            out += ['<details><summary>Published changes and Google status</summary>']
            for p in c['details']:
                out += [f'<div class="ct-product"><a href="{esc(p["url"])}" target="_blank" rel="noopener">{esc(p["title"])}</a>']
                for ch in p['changes']:
                    out.append(f'<p class="ct-note">{esc(ch["published"])} · {esc(ch["field"])} · storefront read-back: {"Verified" if ch.get("verified") else "Not verified"}</p>')
                    if 'before' in ch:
                        out.append(f'<details><summary>Before / after metadata</summary><b>Before</b><div class="ct-copy">{esc(ch["before"] or "No custom description")}</div><b>After</b><div class="ct-copy">{esc(ch["after"])}</div></details>')
                pub=max(ch['published'] for ch in p['changes'])
                base=datetime.date.fromisoformat(pub)
                out.append('<p class="ct-note">Review due: '+ ' · '.join(f'{days}d: {base+datetime.timedelta(days=days)}' for days in [7,14,28])+'</p>')
                out.append(f'<p class="ct-note">Indexing request: {esc(p.get("indexingRequest"))}<br>Google indexed status: {esc(p.get("indexedStatus","Not inspected"))}<br>Last Google crawl: {esc(p.get("lastCrawl") or "Unknown")}<br>Crawl after publication: {esc(p.get("googleRecrawl"))}<br>New content adopted: {esc(p.get("contentAdoption","Not verified"))}</p></div>')
            out.append('</details>')
        else: out.append('<p class="ct-note">No published changes found in the connected change logs. Historical work may be unrecorded.</p>')
        out.append('</details>')
    out+=['<h3>Google crawl and indexing</h3><p class="ct-note">Publication and Google indexing are separate. No new crawl request was submitted in this update. Request Indexing can be used manually in Search Console when needed; the connected analytics tool exposes no submission action. A crawl after publication is evidence of a revisit, not proof Google has adopted every change. Ordinary product pages are not eligible for Google’s restricted Indexing API.</p><details><summary>Sources and limitations</summary>']
    out+=['<p class="ct-note">'+esc(x)+'</p>' for x in d['limitations']]
    out += ['</details></section>',END]
    return '\n'.join(out)
def inject(page,data):
    block=render(data)
    if BEGIN in page:
        if END not in page: raise ValueError('Incomplete existing tracker section')
        return re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END),lambda _:block,page,flags=re.S)
    if '</body>' not in page: raise ValueError('Expected HTML body')
    return page.replace('</body>',block+'\n</body>')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('data');ap.add_argument('--html');a=ap.parse_args()
    d=json.loads(Path(a.data).read_text());key=base64.b64decode(os.environ['SEO_FINAL_KEY']);aes=AESGCM(key);rd=Path(__file__).resolve().parent.parent/'r'
    def decode(path):
        b=path.read_bytes();return gzip.decompress(aes.decrypt(b[:12],b[12:],None)).decode()
    page=inject(decode(rd/'seo-final.bin'),d)
    if a.html:Path(a.html).write_text(page);return
    meta=json.loads(decode(rd/'seo-final.meta.bin'));meta['updated']=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=11))).strftime('%d %b %Y, %H:%M');meta['tracker_updated']=d['asOf']
    encoded=[]
    for name,data in [('seo-final.bin',page.encode()),('seo-final.meta.bin',json.dumps(meta).encode())]:
        iv=os.urandom(12);encoded.append((rd/name,iv+aes.encrypt(iv,gzip.compress(data,9),None)))
    for path,data in encoded:
        temp=path.with_suffix('.tmp');temp.write_bytes(data);temp.replace(path)
    print('Updated encrypted SEO Final tracker and metadata')
if __name__=='__main__':main()
