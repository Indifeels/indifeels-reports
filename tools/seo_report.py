"""Build the encrypted SEO Report for the Indifeels dashboard.

Scores 15 SEO areas (Google Business Profile, organic revenue, rankings, site health and so on) and renders
them as charcoal tiles that open in place (tools/seo_report_template.html).

The numbers come from a JSON file of raw inputs that a Claude scheduled task collects twice a week from
Windsor.ai (Search Console, GA4, Google Business Profile, Google Ads) and Semrush (Site Audit, Position Tracking,
Domain Overview, Backlinks). The inputs are NOT stored in this public repo; only the encrypted output is.
See tools/seo_report_REFRESH.md for the exact input schema and the refresh steps.

Usage:
  python3 tools/seo_report.py DATA.json                 # needs SEO_REPORT_KEY; writes r/seo-report.bin, .meta.bin, status
  python3 tools/seo_report.py DATA.json --html OUT.html # plain preview page, no key, no status
Env: SEO_REPORT_KEY (base64 AES-256 key, from Supabase report_keys)
"""
import argparse
import base64
import datetime as dt
import gzip
import json
import os
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
RDIR = os.path.join(ROOT, "r")
RID = "seo-report"
TZ = ZoneInfo("Australia/Melbourne")
REFRESH_DAYS = (0, 3)  # Monday, Thursday
REFRESH_HOUR = 6

ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--html")
args = ap.parse_args()
D = json.load(open(args.data, encoding="utf-8"))


def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def pct(c, p):
    return (c - p) / p if p else 0


def status(s):
    if s is None:
        return "none"
    return "good" if s >= 70 else ("warn" if s >= 50 else "bad")


def fmt(n):
    return f"{n:,.0f}"


def need(key):
    if key not in D:
        sys.exit(f"input missing: {key}")
    return D[key]


# ---------------------------------------------------------------- inputs
M_calls, M_dirs, M_web = need("M_calls"), need("M_dirs"), need("M_web")
S_calls, S_dirs, S_web = need("S_calls"), need("S_dirs"), need("S_web")
M_imp, S_imp = need("M_imp"), need("S_imp")
reviews, indya, meta = need("reviews"), need("indya"), need("meta")
g_clicks_prev, g_clicks_curr = need("g_clicks_prev"), need("g_clicks_curr")
g_imp_prev, g_imp_curr = need("g_imp_prev"), need("g_imp_curr")
g_pos_prev, g_pos_curr = need("g_pos_prev"), need("g_pos_curr")
queries, named_clicks, pages_qw, top_pages = need("queries"), need("named_clicks"), need("pages_qw"), need("top_pages")
sess, purch, rev = need("sess"), need("purch"), need("rev")
channels, landing_rev, no_sale = need("channels"), need("landing_rev"), need("no_sale")
sem_months, sem_traffic, sem_top3 = need("sem_months"), need("sem_traffic"), need("sem_top3")
comp, indi_traffic = need("comp"), need("indi_traffic")
pt, audit, onp, sitemaps = need("pt"), need("audit"), need("onp"), need("sitemaps")
bl, ads, ai_sessions, fixlists = need("bl"), need("ads"), need("ai_sessions"), need("fixlists")
local_kw, total_kw, aio_kw = need("local_kw"), need("total_kw"), need("aio_kw")

for name, a, n in (("M_calls", M_calls, 46), ("M_dirs", M_dirs, 46), ("M_web", M_web, 46), ("S_calls", S_calls, 46),
                   ("S_dirs", S_dirs, 46), ("S_web", S_web, 46), ("M_imp", M_imp, 23), ("S_imp", S_imp, 23),
                   ("g_clicks_prev", g_clicks_prev, 26), ("g_clicks_curr", g_clicks_curr, 26), ("g_imp_prev", g_imp_prev, 26),
                   ("g_imp_curr", g_imp_curr, 26), ("g_pos_prev", g_pos_prev, 26), ("g_pos_curr", g_pos_curr, 26),
                   ("sess", sess, 56), ("purch", purch, 56), ("rev", rev, 56), ("sem_traffic", sem_traffic, 12),
                   ("sem_top3", sem_top3, 12), ("sem_months", sem_months, 12)):
    if len(a) != n:
        sys.exit(f"input {name} should have {n} values, has {len(a)}")

# ---------------------------------------------------------------- GBP
loc = {}
for name, c, d, w in (("Melbourne", M_calls, M_dirs, M_web), ("Sydney", S_calls, S_dirs, S_web)):
    loc[name] = dict(calls=sum(c[23:]), calls_prev=sum(c[:23]), dirs=sum(d[23:]), dirs_prev=sum(d[:23]),
                     web=sum(w[23:]), web_prev=sum(w[:23]))
calls_c = sum(l["calls"] for l in loc.values()); calls_p = sum(l["calls_prev"] for l in loc.values())
dirs_c = sum(l["dirs"] for l in loc.values()); web_c = sum(l["web"] for l in loc.values())
dirs_p = sum(l["dirs_prev"] for l in loc.values()); web_p = sum(l["web_prev"] for l in loc.values())
act_c, act_p = calls_c + dirs_c + web_c, calls_p + dirs_p + web_p
act_pct = pct(act_c, act_p)
tot_daily = [M_calls[i]+M_dirs[i]+M_web[i]+S_calls[i]+S_dirs[i]+S_web[i] for i in range(46)]
gbp_weekly = [sum(tot_daily[4+7*k:4+7*(k+1)]) for k in range(6)]


def imp_sum(rows):
    return [sum(r[i] for r in rows) for i in range(4)]


imp_M, imp_S = imp_sum(M_imp), imp_sum(S_imp)
rm, rs = reviews["mel"], reviews["syd"]
rating_total = (rm["n"]*rm["rating"] + rs["n"]*rs["rating"]) / (rm["n"] + rs["n"])
rating_score = clamp((rating_total - 4.0) * 100)
trend_score = clamp(50 + act_pct * 100)
reviews_28 = rm["new28"] + rs["new28"]
review_score = clamp(reviews_28 / 10 * 100)
gbp_score = round(0.4*rating_score + 0.4*trend_score + 0.2*review_score)

# ---------------------------------------------------------------- GSC
gc_p, gc_c = sum(g_clicks_prev), sum(g_clicks_curr)
gi_p, gi_c = sum(g_imp_prev), sum(g_imp_curr)
gp_p = sum(p*i for p, i in zip(g_pos_prev, g_imp_prev)) / gi_p
gp_c = sum(p*i for p, i in zip(g_pos_curr, g_imp_curr)) / gi_c
gsc_click_pct = pct(gc_c, gc_p)
brand_re = re.compile(r"indi\s?feels")
q_rows = [dict(q=q, clicks=c, imp=i, ctr=(c / i if i else 0), pos=p, brand=bool(brand_re.search(q))) for q, c, i, p in queries]
TARGET_CTR = 0.09
quick = []
for r in q_rows:
    if r["brand"]:
        continue
    if 4 <= r["pos"] <= 20 and r["imp"] >= 100:
        gain = r["imp"] * (TARGET_CTR - r["ctr"])
        if gain > 0:
            quick.append(dict(r, gain=round(gain)))
quick.sort(key=lambda r: -r["gain"])
quick_top = quick[:10]
quick_total = sum(r["gain"] for r in quick_top)
brand_clicks = sum(r["clicks"] for r in q_rows if r["brand"])
brand_share = brand_clicks / named_clicks
quick_score = round(clamp(100 - quick_total / named_clicks * 100, 20, 100))
pages_rows = [dict(page=p, clicks=c, imp=i, ctr=c/i, pos=pos) for p, c, i, pos in pages_qw]
kw_share_score = clamp(pt["top10"] / pt["tracked"] / 0.40 * 100)
kw_trend_score = clamp(50 + gsc_click_pct * 100)
kw_score = round((kw_share_score + kw_trend_score) / 2)

# ---------------------------------------------------------------- GA4 organic
s_p, s_c = sum(sess[:28]), sum(sess[28:])
o_p, o_c = sum(purch[:28]), sum(purch[28:])
r_p, r_c = sum(rev[:28]), sum(rev[28:])
rev_weekly = [sum(rev[7*k:7*(k+1)]) for k in range(8)]
cr_c = o_c / s_c
rev_pct = pct(r_c, r_p)
sess_pct = pct(s_c, s_p)
rev_score = round((clamp(50 + rev_pct * 50) + clamp(cr_c / 0.01 * 100)) / 2)
traffic_score = round(clamp(50 + ((sess_pct + gsc_click_pct) / 2) * 100))

# ---------------------------------------------------------------- Semrush
traffics = sorted(c[3] for c in comp)
n = len(traffics)
median_rival = traffics[n // 2] if n % 2 else (traffics[n // 2 - 1] + traffics[n // 2]) / 2
comp_score = round(clamp(indi_traffic / median_rival * 100))
pages_crawled, errors, warnings, notices = audit["pages"], audit["errors"], audit["warnings"], audit["notices"]
health_score = round(clamp(100 - errors / pages_crawled * 100 * 5 - warnings / pages_crawled * 100 * 0.5))
onp_penalty = sum(c / pages_crawled * 100 * w for _, c, w in onp)
onpage_score = round(clamp(100 - onp_penalty))
shop_pen = (0 if audit.get("schema_found") else 15) + (15 if audit["deep"]/pages_crawled > .20 else 0) \
    + (10 if audit["one_link"]/pages_crawled > .20 else 0) + (5 if audit.get("dup_pages", 0) > 0 else 0) \
    + (5 if audit["redirected"]/pages_crawled > .05 else 0)
shop_score = round(clamp(100 - shop_pen))
backlink_score = round(clamp(bl["authority"] / 40 * 100))
local_share = local_kw / total_kw
local_score = round(clamp(local_share / 0.30 * 100))
stale_err = sum(1 for s in sitemaps if s[5] == "stale" and s[2] > 0)
index_score = round(clamp(90 - min(35, 5 * stale_err)))
ads_clicks = sum(a[1] for a in ads); ads_cost = sum(a[2] for a in ads); ads_conv = sum(a[3] for a in ads)
org_clicks_same = sum(a[5] for a in ads)
paid_score = 60
ai_share = ai_sessions / s_c
ai_score = round(clamp(ai_share / 0.05 * 100))

# ---------------------------------------------------------------- tiles
tiles = []


def trend(p, up_good=True):
    if p is None:
        return None
    return dict(dir=("up" if p >= 0 else "down"), text=f"{abs(p)*100:.0f}%", good=((p >= 0) == up_good))


def add(**k):
    k["status"] = status(k.get("score"))
    tiles.append(k)


M, S = loc["Melbourne"], loc["Sydney"]
add(id="gbp", title="Calls & Google Business Profile", score=gbp_score, accent="a1",
    key=fmt(calls_c), keyLabel="call taps · 23 days", sub=f"{fmt(dirs_c)} directions · {fmt(web_c)} site clicks",
    trend=trend(pct(calls_c, calls_p)), spark=gbp_weekly,
    how="40% rating (4.0 = 0, 5.0 = 100) + 40% profile actions vs previous 23 days + 20% new reviews (10 in 28 days = 100).",
    d=dict(loc=loc, act_c=act_c, act_p=act_p, imp_M=imp_M, imp_S=imp_S, weekly=gbp_weekly, rating=round(rating_total, 2)))
add(id="revenue", title="Organic revenue & orders", score=rev_score, accent="a4",
    key=f"${fmt(r_c)}", keyLabel="organic search revenue · 28 days", sub=f"{o_c} orders · {cr_c*100:.2f}% conversion",
    trend=trend(rev_pct), spark=rev_weekly, spark_kind="bars",
    how="Half revenue trend vs previous 28 days, half organic conversion rate (1.0% = 100). Only a handful of orders per period, so treat it as direction, not proof.",
    d=dict(s_c=s_c, s_p=s_p, o_c=o_c, o_p=o_p, r_c=r_c, r_p=r_p, channels=channels, landing=landing_rev, no_sale=no_sale))
add(id="keywords", title="Keyword rankings", score=kw_score, accent="a2",
    key=fmt(gc_c), keyLabel="Google organic clicks · 26 days", sub=f"avg position {gp_c:.1f} (was {gp_p:.1f})",
    trend=trend(gsc_click_pct), spark=g_clicks_prev + g_clicks_curr,
    how="Half share of tracked keywords in the top 10 (40% = 100), half click trend vs previous 26 days.",
    d=dict(gc_c=gc_c, gc_p=gc_p, gi_c=gi_c, gi_p=gi_p, gp_c=gp_c, gp_p=gp_p,
           queries=sorted(q_rows, key=lambda r: (-r["clicks"], -r["imp"]))[:14], brand_share=brand_share))
add(id="local", title="Local pack rankings", score=local_score, accent="a1", partial=True,
    key=fmt(local_kw), keyLabel="keywords in the Local Pack", sub=f"{local_share*100:.0f}% of your {fmt(total_kw)} ranking keywords",
    trend=None, split=[imp_M[1]+imp_S[1]+imp_M[3]+imp_S[3], imp_M[0]+imp_S[0]+imp_M[2]+imp_S[2]],
    how="Share of ranking keywords that show you in the Local Pack (30% = 100). Position-by-position local tracking is not available yet.",
    d=dict(imp_M=imp_M, imp_S=imp_S))
add(id="health", title="Site health", score=health_score, accent="a3",
    key=fmt(errors), keyLabel="errors", sub=f"{fmt(warnings)} warnings · {fmt(pages_crawled)} pages crawled",
    trend=None, seg=[("Clean", audit["clean"], "good"), ("Redirected", audit["redirected_pages"], "a2"),
                     ("Broken", audit["broken"], "bad"), ("Other issues", audit["flagged"], "warn")],
    how="100 minus errors (5 points per 1% of pages) minus warnings (0.5 points per 1% of pages). Notices are not scored.",
    d=dict(errors=errors, warnings=warnings, notices=notices, pages=pages_crawled, p_clean=audit["clean"],
           p_redir=audit["redirected_pages"], p_broken=audit["broken"], p_flag=audit["flagged"], err_types=audit["err_types"]))
add(id="quick", title="Quick wins", score=quick_score, accent="a4",
    key=f"+{fmt(quick_total)}", keyLabel="clicks per 4 weeks, top 10 queries", sub="if they moved to the top 3 (rough)",
    trend=None, bars=[(r["q"], r["gain"]) for r in quick_top[:5]],
    how="100 minus the extra clicks as a % of today's named-query clicks (floor 20). Gain = impressions x (9% - current CTR) for non-brand queries at positions 4-20.",
    d=dict(quick=quick_top, total=quick_total, pages=pages_rows))
add(id="traffic", title="Organic traffic trend", score=traffic_score, accent="a2",
    key=fmt(s_c), keyLabel="organic search sessions · 28 days", sub=f"{fmt(s_p)} in the 28 days before",
    trend=trend(sess_pct), spark=sess,
    how="50 plus the average of GA4 session change and Search Console click change (+10% = +10 points).",
    d=dict(s_c=s_c, s_p=s_p, gc_c=gc_c, gc_p=gc_p, sem_months=sem_months, sem_traffic=sem_traffic, sem_top3=sem_top3, top_pages=top_pages))
add(id="competitors", title="Competitors", score=comp_score, accent="a3",
    key=fmt(indi_traffic), keyLabel="est. monthly organic visits", sub=f"typical rival: {fmt(median_rival)}",
    trend=None, bars2=[("Indifeels", indi_traffic)] + [(c[0], c[3]) for c in sorted(comp, key=lambda c: -c[3])[:2]],
    how="Your estimated organic traffic as a % of the median of the closest rivals (100 = level with the median).",
    d=dict(comp=comp, indi_traffic=indi_traffic, median=median_rival))
add(id="indexing", title="Indexing & sitemaps", score=index_score, accent="a1", partial=True,
    key=f"{stale_err}", keyLabel="stale sitemaps with errors", sub="live sitemaps are healthy",
    trend=None, dots=[s[5] if s[5] == "live" else ("bad" if s[2] > 0 else "warn") for s in sitemaps],
    how="90 if the live sitemap is healthy, minus 5 for each stale sitemap still showing errors (max 35). Page indexing coverage is not available through Windsor.",
    d=dict(sitemaps=sitemaps, orphan=audit["orphan_sm"]))
add(id="cwv", title="Core Web Vitals", score=None, accent="a2",
    key="No data", keyLabel="not connected yet", sub="LCP · CLS · INP", trend=None,
    how="Not scored until a data source is connected.", d={})
add(id="shopify", title="Shopify specifics", score=shop_score, accent="a3", partial=True,
    key=fmt(audit["deep"]), keyLabel="pages more than 3 clicks deep", sub="structured data not detected by the crawler",
    trend=None, bars=[("Deep pages", round(audit["deep"]/pages_crawled*100)), ("Single link", round(audit["one_link"]/pages_crawled*100)),
                      ("Redirected", round(audit["redirected"]/pages_crawled*100)), ("Not linked", round(audit["orphan_sm"]/pages_crawled*100))],
    bars_unit="%",
    how="100 minus 15 (no structured data found) minus 15 (more than 20% of pages deep) minus 10 (more than 20% with one internal link) minus 5 (duplicate content) minus 5 (more than 5% redirected).",
    d=dict(deep=audit["deep"], one_link=audit["one_link"], redirected=audit["redirected"], orphan=audit["orphan_sm"], pages=pages_crawled))
no_meta = next((c for nme, c, _ in onp if nme == "Missing meta description"), 0)
no_h1 = next((c for nme, c, _ in onp if nme == "Missing H1"), 0)
add(id="onpage", title="On-page SEO", score=onpage_score, accent="a4",
    key=fmt(no_meta), keyLabel="pages missing a meta description", sub=f"{no_h1} pages have no H1",
    trend=None, bars=[(nme, round(c/pages_crawled*100)) for nme, c, _ in onp[:4]], bars_unit="%",
    how="100 minus the % of pages with each issue (missing meta and missing H1 at full weight, the rest at half).",
    d=dict(onp=[(nme, c, c/pages_crawled*100) for nme, c, _ in onp], pages=pages_crawled, no_meta=no_meta, no_h1=no_h1,
           no_meta_pct=round(no_meta/pages_crawled*100), no_h1_pct=round(no_h1/pages_crawled*100)))
add(id="backlinks", title="Backlinks", score=backlink_score, accent="a2", partial=True,
    key=fmt(bl["domains"]), keyLabel="referring domains", sub=f"Authority Score {bl['authority']}",
    trend=None, split2=[("Follow", bl["follow"]), ("Nofollow", bl["nofollow"])],
    how="Semrush Authority Score scaled so that 40 = 100. New and lost link trends are not available yet.",
    d=dict(domains=bl["domains"], links=bl["links"], authority=bl["authority"], follow=bl["follow"], nofollow=bl["nofollow"]))
add(id="paid", title="Organic vs paid gap", score=paid_score, accent="a1", partial=True,
    key=f"${ads_cost:,.0f}", keyLabel="spend on brand searches · 28 days", sub=f"{ads_clicks} clicks · {ads_conv} conversions",
    trend=None, vs=[("Paid clicks", ads_clicks), ("Organic clicks", org_clicks_same)],
    how="60 because all visible paid search-term spend is on queries where you already rank first or second. Brand ads also block rivals, so this is a prompt to test, not a cut.",
    d=dict(ads=ads, ads_clicks=ads_clicks, ads_cost=round(ads_cost, 2), ads_conv=ads_conv, org=org_clicks_same))
add(id="ai", title="AI search visibility", score=ai_score, accent="a3",
    key=fmt(ai_sessions), keyLabel="visits from AI assistants · 28 days", sub=f"{ai_share*100:.1f}% of organic search sessions",
    trend=None, ring=round(ai_share*100, 1),
    how="AI assistant sessions as a % of organic search sessions (5% = 100).",
    d=dict(sessions=ai_sessions, share=ai_share))

for i, t in enumerate(tiles, 1):
    t["rank"] = i
scored = [t for t in tiles if t["score"] is not None]
weights = {t["id"]: 16 - t["rank"] for t in tiles}
overall = round(sum(t["score"] * weights[t["id"]] for t in scored) / sum(weights[t["id"]] for t in scored))

# ---------------------------------------------------------------- refresh times
now = dt.datetime.now(TZ)
if os.environ.get("SEO_NOW"):
    now = dt.datetime.fromisoformat(os.environ["SEO_NOW"]).astimezone(TZ)


def next_refresh(after):
    for add_days in range(0, 8):
        d = (after + dt.timedelta(days=add_days)).replace(hour=REFRESH_HOUR, minute=0, second=0, microsecond=0)
        if d.weekday() in REFRESH_DAYS and d > after:
            return d
    return after


def stamp(d):
    return d.strftime("%a %d %b, %-I:%M %p").replace("AM", "am").replace("PM", "pm")


live = [s for s in sitemaps if s[5] == "live"]
live_urls = sum(s[1] for s in live)
facts = dict(
    refreshed=stamp(now), next_refresh=stamp(next_refresh(now)),
    gbp_start=meta["gbp_start"], gbp_end=meta["gbp_end"], audit_date=meta["audit_date"],
    reviews_text=f"{rm['n'] + rs['n']} reviews, both stores", new_total=str(reviews_28),
    new_text=f"Melbourne {rm['new28']} · Sydney {rs['new28']} (28 days)",
    indya_mel=indya["mel"], indya_syd=indya["syd"],
    kw_note=f"Semrush tracks {pt['tracked']} keywords: {pt['top3']} in the top 3 ({pt['top3_d']:+d}) and {pt['top10']} in the top 10 ({pt['top10_d']:+d}); visibility {pt['vis']:.1f}%.",
    local_kw=local_kw, total_kw=total_kw, aio_kw=aio_kw,
    live_n=str(len(live)), live_text=f"{fmt(live_urls)} URLs, no errors" if all(s[2] == 0 for s in live) else f"{fmt(live_urls)} URLs, errors found",
    old_n=str(len(sitemaps) - len(live)), ai_orders=str(meta.get("ai_orders", 0)),
)
data = dict(overall=overall, scoredCount=len(scored), total=len(tiles), tiles=tiles, fixlists=fixlists, facts=facts,
            counts=dict(good=sum(1 for t in tiles if t["status"] == "good"), warn=sum(1 for t in tiles if t["status"] == "warn"),
                        bad=sum(1 for t in tiles if t["status"] == "bad")))

tpl = open(os.path.join(TOOLS, "seo_report_template.html"), encoding="utf-8").read()
PRE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>html,body{margin:0}</style>')
page = PRE + tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")) + "</html>"

print(f"overall {overall} | refreshed {facts['refreshed']} | next {facts['next_refresh']}")
for t in tiles:
    print(f"  #{t['rank']} {t['id']}: {t['score']}")

if args.html:
    open(args.html, "w", encoding="utf-8").write(page)
    print("wrote", args.html)
    sys.exit(0)

# ---------------------------------------------------------------- encrypt + publish files
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

key_b64 = os.environ.get("SEO_REPORT_KEY", "")
key = base64.b64decode(key_b64) if key_b64 else b""
if len(key) != 32:
    sys.exit("SEO_REPORT_KEY is missing or not a 32-byte AES key")


def enc(payload):
    iv = os.urandom(12)
    return iv + AESGCM(key).encrypt(iv, gzip.compress(payload, 9), None)


st = "good" if overall >= 70 else ("hold" if overall >= 50 else "down")
worst = sorted(scored, key=lambda t: t["score"])[:1][0]
tile_meta = dict(
    updated=now.strftime("%d %b %Y, %H:%M"),
    stats=[[str(overall), "overall SEO score"], [str(calls_c), "Google profile call taps"],
           [f"${fmt(r_c)}", "organic revenue, 28 days"], [str(errors), "site errors"]],
    signal=dict(code={"good": "up", "hold": "hold", "down": "down"}[st], label=f"SCORE {overall}",
                reason=f"Weakest area: {worst['title']} ({worst['score']})."),
    warn=f"{errors} site errors to fix" if errors else "",
    spark=gbp_weekly,
)
os.makedirs(RDIR, exist_ok=True)
open(os.path.join(RDIR, f"{RID}.bin"), "wb").write(enc(page.encode("utf-8")))
open(os.path.join(RDIR, f"{RID}.meta.bin"), "wb").write(enc(json.dumps(tile_meta).encode("utf-8")))
subprocess.run([sys.executable, os.path.join(TOOLS, "status.py"), RDIR, RID, "ok"], check=True)
print("wrote r/seo-report.bin, r/seo-report.meta.bin")
