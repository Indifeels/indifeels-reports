"""Build the live Google Ads tracked report and its tile metadata."""
import datetime as dt
import html
import json
import os
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

SRC, OUT_HTML, OUT_META = sys.argv[1:4]
x = json.load(open(SRC))
rows = x["data"] if isinstance(x, dict) else x
TZ = ZoneInfo("Australia/Sydney")
NOW = dt.datetime.now(TZ)
if os.environ.get("REPORT_NOW"):
    NOW = dt.datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)
END = NOW.date()
CONTRIB = 0.75 / 1.1
BREAK_EVEN_ROAS = 1 / CONTRIB

def num(v):
    try: return float(v or 0)
    except: return 0.0

daily = defaultdict(lambda: dict(spend=0.0, revenue=0.0, conversions=0.0, clicks=0.0, impressions=0.0))
campaigns = defaultdict(lambda: dict(spend=0.0, revenue=0.0, conversions=0.0, clicks=0.0, impressions=0.0, status="", last_share=None, last_budget_lost=None, last_rank_lost=None, last_date=""))

for r in rows:
    name = str(r.get("campaign") or "")
    if not name.lower().startswith("tracked_"):
        continue
    d = str(r.get("date") or "")
    if not d:
        continue
    s, rev = num(r.get("spend")), num(r.get("conversions_value"))
    cv, cl, im = num(r.get("conversions")), num(r.get("clicks")), num(r.get("impressions"))
    z = daily[d]
    z["spend"] += s; z["revenue"] += rev; z["conversions"] += cv; z["clicks"] += cl; z["impressions"] += im
    c = campaigns[name]
    c["spend"] += s; c["revenue"] += rev; c["conversions"] += cv; c["clicks"] += cl; c["impressions"] += im
    c["status"] = str(r.get("campaign_status") or c["status"])
    if d >= c["last_date"]:
        c["last_date"] = d
        c["last_share"] = r.get("search_impression_share")
        c["last_budget_lost"] = r.get("search_budget_lost_impression_share")
        c["last_rank_lost"] = r.get("search_rank_lost_impression_share")

def finish(v):
    v = dict(v)
    v["profit"] = v["revenue"] * CONTRIB - v["spend"]
    v["roas"] = (v["revenue"] / v["spend"]) if v["spend"] else None
    v["cpc"] = (v["spend"] / v["clicks"]) if v["clicks"] else None
    v["conv_rate"] = (v["conversions"] / v["clicks"]) if v["clicks"] else None
    return v

daily = {d: finish(v) for d, v in daily.items()}
campaigns = {n: finish(v) | {k:v[k] for k in ("status","last_share","last_budget_lost","last_rank_lost","last_date")} for n,v in campaigns.items()}

def dates(a, b):
    out=[]; d=a
    while d<=b:
        out.append(d.isoformat()); d += dt.timedelta(days=1)
    return out

def aggregate(a, b):
    out=dict(spend=0.0,revenue=0.0,conversions=0.0,clicks=0.0,impressions=0.0)
    for d in dates(a,b):
        v=daily.get(d)
        if not v: continue
        for k in out: out[k]+=v[k]
    return finish(out)

d1 = daily.get(END.isoformat(), finish({k:0.0 for k in ("spend","revenue","conversions","clicks","impressions")}))
d7 = aggregate(END-dt.timedelta(days=6), END)
d30 = aggregate(END-dt.timedelta(days=29), END)

if d7["spend"] and d7["roas"] is not None:
    if d7["profit"] > 0 and d7["roas"] >= 2:
        sig, reason = "Profitable", f"Last 7 days ROAS is {d7['roas']:.2f}x with provisional profit " + "$" + f"{d7['profit']:,.0f}."
    elif d7["roas"] >= BREAK_EVEN_ROAS:
        sig, reason = "Above break-even", f"Last 7 days ROAS is {d7['roas']:.2f}x versus break-even about {BREAK_EVEN_ROAS:.2f}x."
    else:
        sig, reason = "Below break-even", f"Last 7 days ROAS is {d7['roas']:.2f}x, below break-even about {BREAK_EVEN_ROAS:.2f}x."
else:
    sig, reason = "No tracked revenue", "No tracked Google Ads revenue is recorded in the last 7 days."

def money(v, dp=0):
    return ("−" if v < 0 else "") + "$" + f"{abs(v):,.{dp}f}"

def pct(v):
    return "—" if v is None else f"{float(v)*100:.1f}%"

def roas(v):
    return "—" if v is None else f"{v:.2f}x"

def esc(s): return html.escape(str(s))

recent_dates = dates(END-dt.timedelta(days=29), END)
spark=[round(daily.get(d,{"profit":0})["profit"],2) for d in recent_dates]

meta = {
    "updated": NOW.strftime("%-d %b %Y, %-I:%M %p"),
    "stats": [
        [money(d1["profit"],2), f"provisional profit {END.strftime('%-d %b')}"],
        [roas(d1["roas"]), f"ROAS {END.strftime('%-d %b')}"],
        [money(d7["profit"],2), "provisional profit, last 7 days"],
        [money(d30["profit"],2), "provisional profit, last 30 days"],
    ],
    "signal": {"code":"hold","label":"Tracked Google Ads","reason":reason},
    "spark": spark,
}
json.dump(meta, open(OUT_META,"w"), separators=(",",":"))

c30 = defaultdict(lambda: dict(spend=0.0,revenue=0.0,conversions=0.0,clicks=0.0,impressions=0.0,status="",last_share=None,last_budget_lost=None,last_rank_lost=None,last_date=""))
lo=(END-dt.timedelta(days=29)).isoformat()
hi=END.isoformat()
for r in rows:
    d=str(r.get("date") or "")
    name=str(r.get("campaign") or "")
    if not (lo <= d <= hi) or not name.lower().startswith("tracked_"): continue
    c=c30[name]
    c["spend"]+=num(r.get("spend")); c["revenue"]+=num(r.get("conversions_value")); c["conversions"]+=num(r.get("conversions")); c["clicks"]+=num(r.get("clicks")); c["impressions"]+=num(r.get("impressions"))
    c["status"]=str(r.get("campaign_status") or c["status"])
    if d>=c["last_date"]:
        c["last_date"]=d
        c["last_share"]=r.get("search_impression_share")
        c["last_budget_lost"]=r.get("search_budget_lost_impression_share")
        c["last_rank_lost"]=r.get("search_rank_lost_impression_share")
c30={n:finish(v)|{k:v[k] for k in ("status","last_share","last_budget_lost","last_rank_lost","last_date")} for n,v in c30.items()}

camp_rows=""
for name,v in sorted(c30.items(), key=lambda kv: kv[1]["spend"], reverse=True):
    short=name.replace("Tracked_MM_","").replace("_Campaign_"," · ").replace("_"," ")
    camp_rows += f"""<tr><td><b>{esc(short)}</b><small>{esc(v['status'])}</small></td><td>{money(v['spend'],2)}</td><td>{money(v['revenue'],0)}</td><td>{roas(v['roas'])}</td><td>{money(v['profit'],2)}</td><td>{v['conversions']:.1f}</td><td>{pct(v['last_share'])}</td><td>{pct(v['last_budget_lost'])}</td><td>{pct(v['last_rank_lost'])}</td></tr>"""

day_rows=""
for d in reversed(recent_dates):
    v=daily.get(d,finish({k:0.0 for k in ("spend","revenue","conversions","clicks","impressions")}))
    day_rows += f"""<tr><td>{dt.date.fromisoformat(d).strftime('%-d %b')}</td><td>{money(v['spend'],2)}</td><td>{money(v['revenue'],0)}</td><td>{roas(v['roas'])}</td><td class="{'pos' if v['profit']>=0 else 'neg'}">{money(v['profit'],2)}</td><td>{v['conversions']:.1f}</td><td>{int(v['clicks'])}</td><td>{int(v['impressions']):,}</td></tr>"""

def card(label,v,sub=""):
    return f'<div class="card"><span>{esc(label)}</span><strong>{esc(v)}</strong><small>{esc(sub)}</small></div>'

cards = "".join([
    card(f"Profit · {END.strftime('%-d %b')}", money(d1["profit"],2), f"Revenue {money(d1['revenue'],0)} · Spend {money(d1['spend'],2)}"),
    card(f"ROAS · {END.strftime('%-d %b')}", roas(d1["roas"]), f"{d1['conversions']:.1f} tracked conversions"),
    card("Last 7 days", money(d7["profit"],2), f"ROAS {roas(d7['roas'])} · Spend {money(d7['spend'],0)}"),
    card("Last 30 days", money(d30["profit"],2), f"ROAS {roas(d30['roas'])} · Revenue {money(d30['revenue'],0)}"),
])

page=f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Google Ads tracked · IndiFeels</title>
<style>
:root{{--bg:#f3f6fb;--card:#fff;--ink:#111827;--muted:#667085;--line:#dce3ec;--good:#067647;--bad:#b42318;--accent:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#070b18;--card:#10182b;--ink:#f3f5fb;--muted:#a6b0c3;--line:#27324a;--good:#75e0ad;--bad:#ff9b92;--accent:#7aa7ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:auto;padding:22px 14px 50px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}}h1{{font-size:28px;margin:0 0 4px}}p{{margin:0;color:var(--muted)}}.pill{{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:8px 12px;font-weight:700;white-space:nowrap}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px}}.card span,.card small{{display:block;color:var(--muted)}}.card strong{{display:block;font-size:24px;margin:4px 0 2px}}.panel{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin-top:14px;overflow:auto}}h2{{font-size:17px;margin:0 0 10px}}.signal{{display:flex;gap:10px;align-items:flex-start}}.signal b{{background:var(--accent);color:white;border-radius:999px;padding:5px 10px;white-space:nowrap}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:12px}}td small{{display:block;color:var(--muted);font-size:11px}}.pos{{color:var(--good);font-weight:700}}.neg{{color:var(--bad);font-weight:700}}.note{{font-size:12px;margin-top:10px;color:var(--muted)}}@media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:23px}}header{{display:block}}.pill{{display:inline-block;margin-top:10px}}}}
</style></head><body><main>
<header><div><h1>Google Ads tracked</h1><p>Live tracked-campaign performance from Windsor.ai. Data through {END.strftime('%-d %b %Y')}.</p></div><span class="pill">Updated {NOW.strftime('%-I:%M %p')}</span></header>
<section class="cards">{cards}</section>
<section class="panel"><div class="signal"><b>{esc(sig)}</b><p>{esc(reason)} Profit uses the IndiFeels contribution model: revenue less GST and 25% product cost, then ad spend.</p></div></section>
<section class="panel"><h2>Campaign performance · last 30 days</h2><table><thead><tr><th>Campaign</th><th>Spend</th><th>Tracked revenue</th><th>ROAS</th><th>Profit</th><th>Conv.</th><th>Search IS</th><th>Lost · budget</th><th>Lost · rank</th></tr></thead><tbody>{camp_rows}</tbody></table></section>
<section class="panel"><h2>Daily performance · last 30 days</h2><table><thead><tr><th>Date</th><th>Spend</th><th>Tracked revenue</th><th>ROAS</th><th>Profit</th><th>Conv.</th><th>Clicks</th><th>Impr.</th></tr></thead><tbody>{day_rows}</tbody></table>
<p class="note">Tracked campaigns are campaigns whose Google Ads campaign name begins with “Tracked_”. Break-even ROAS is about {BREAK_EVEN_ROAS:.2f}x under the current contribution assumptions.</p></section>
</main></body></html>"""
open(OUT_HTML,"w").write(page)
print("Google tracked report built through", END.isoformat(), "with", len(c30), "campaigns")
