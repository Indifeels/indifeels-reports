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
spd, msd, rvd, odd = {}, {}, {}, {}
for r in rows_in:
    if not tracked(r.get("campaign")): continue
    d = r["date"]
    spd[d] = spd.get(d, 0) + (r.get("spend") or 0)
    msd[d] = msd.get(d, 0) + (r.get("clicks") or 0)
    rvd[d] = rvd.get(d, 0) + (r.get("action_values_purchase") or 0)
    odd[d] = odd.get(d, 0) + (r.get("actions_purchase") or 0)
sp, ms, rv, od = {}, {}, {}, {}
for d in spd:
    k = d[:7]; sp[k] = sp.get(k, 0) + spd[d]; ms[k] = ms.get(k, 0) + msd[d]
    rv[k] = rv.get(k, 0) + rvd.get(d, 0); od[k] = od.get(k, 0) + odd.get(d, 0)
months = [k for k in sorted(sp) if k >= "2026-03"]
TRACK_START = dt.date.fromisoformat(min(d for d in rvd if rvd[d] > 0)).replace(day=1)

# signal engine, shared verbatim with monthly.py
eng = src.split("# ===== SIGNAL ENGINE (profit-maximisation) — BEGIN =====")[1].split("# ===== SIGNAL ENGINE — END =====")[0]
exec(eng)
_orig_signal_for = signal_for
def _cl(t):
    return (t.replace("messages to orders", "clicks to orders").replace("Messages to orders", "Clicks to orders")
             .replace("Revenue per message", "Sales per click").replace("revenue per message", "sales per click")
             .replace("cost per message", "cost per click").replace("Cost per message", "Cost per click")
             .replace("messages per day", "clicks per day").replace("messages", "clicks").replace("message", "click")
             .replace("attributed orders", "tracked orders").replace("revenue", "sales").replace("Revenue", "Sales"))
def signal_for(*a, **k):
    o = _orig_signal_for(*a, **k)
    o["reason"] = _cl(o["reason"]); o["details"] = [_cl(x) for x in o["details"]]
    return o

YDAY = NOW.date() - dt.timedelta(1)
def month_sig(k):
    ms_ = dt.date.fromisoformat(k + "-01"); me_ = ms_.replace(day=_cal.monthrange(ms_.year, ms_.month)[1])
    if me_ >= NOW.date(): return rolling_signal(YDAY)
    pe_ = ms_ - dt.timedelta(1); ps_ = pe_.replace(day=1)
    return month_signal(ms_, me_, ps_, pe_)
def dv(a, b): return a / b if b else None
def calc(s, m, r, o):
    p = r / 1.1 * 0.75 - s
    return dict(s=s, r=r, roas=dv(r, s), spm=dv(s, m), rpm=dv(r, m), mto=dv(o * 100, m), np=p, npm=dv(p, m),
                o=o, m=m, cpo=dv(s, o), be=dv(r * 0.75 / 1.1, m), sig=None)
rows = [(dt.date.fromisoformat(k + "-01").strftime("%b %Y") + ("*" if k == NOW.strftime("%Y-%m") else ""), calc(sp[k], ms[k], rv.get(k, 0), od.get(k, 0))) for k in months]
for (_n, _d), _k in zip(rows, months): _d["sig"] = month_sig(_k)
T = calc(sum(sp[k] for k in months), sum(ms[k] for k in months), sum(rv.get(k, 0) for k in months), sum(od.get(k, 0) for k in months))
def m0(v): return ("−" if v < 0 else "") + f"${abs(v):,.0f}"
def m2(v): return ("−" if v < 0 else "") + f"${abs(v):,.2f}"
COLS = [("s", "Spend", lambda v: f"${v:,.0f}", None, None),
        ("m", "Clicks", lambda v: f"{int(v):,}", None, True),
        ("spm", "Cost per click", lambda v: f"${v:.2f}", (0.40, 0.60), False),
        ("r", "Tracked sales", lambda v: f"${v:,.0f}", None, True),
        ("rpm", "Sales per click", lambda v: f"${v:.2f}", (1.20, 0.80), True),
        ("roas", "ROAS", lambda v: f"{v:.2f}x", (2.0, 1.4727), True),
        ("mto", "Clicks to orders", lambda v: f"{v:.1f}%", (2.0, 1.0), True),
        ("o", "Orders", lambda v: f"{v:,.0f}", None, True),
        ("cpo", "Cost per order", lambda v: f"${v:,.2f}", None, False),
        ("npm", "Net profit per click", m2, (0.30, 0), True),
        ("np", "Net profit", m0, (1000, 0), True),
        ("be", "Break-even per click", lambda v: f"${v:.2f}", None, True),
        ("sig", "Signal", None, None, None)]
def band(v, b, hb):
    if not b or v is None: return ""
    g, y = b
    if hb: return "g" if v >= g else "y" if v >= y else "r"
    return "g" if v < g else "y" if v <= y else "r"
def arr(v, pv, sense):
    if pv is None or v is None or round(v, 4) == round(pv, 4): return '<i class="a"></i>'
    up = v > pv; cls = "n" if sense is None else ("gd" if up == sense else "bd")
    return f'<i class="a {cls}" title="{"Up" if up else "Down"} on previous month">{"▲" if up else "▼"}</i>'
DAYB = {"np": (33, 0)}
SIGL = {"up": "Scale Up", "hold": "Hold", "down": "Scale Down"}; SIGC = {"up": "scale", "hold": "hold", "down": "cut"}
def cells(d, prev, day=False, npb=None):
    out = ""
    for k, _, f, b, sense in COLS:
        if k == "sig":
            sg = d.get("sig")
            if sg and sg.get("code") and not day:
                out += f'<td><button type="button" class="sgc {SIGC[sg["code"]]}" aria-expanded="false" data-sd="{d.get("_id","")}" title="Show why">{SIGL[sg["code"]]} <span aria-hidden="true">ⓘ</span></button></td>'
            elif sg and not day:
                out += f'<td><span class="v none" title="{html.escape(sg["reason"])}">—</span></td>'
            else: out += '<td><span class="v none">—</span></td>'
            continue
        if k == "be" and day:
            out += '<td><span class="v none">—</span></td>'; continue
        if day and k in DAYB: b = npb if npb else DAYB[k]
        if d[k] is None:
            out += '<td><span class="v none">' + ("No clicks" if k in ("spm", "rpm", "mto", "npm") and d["s"] else "No orders" if k == "cpo" and d["s"] else "—") + '</span><i class="a"></i></td>'; continue
        hb = [c[4] for c in COLS if c[0] == k][0]
        bd = band(d[k], b, hb)
        dot = f'<span class="d {bd}"></span>' if bd else ""
        out += f'<td><span class="v {bd}">{dot}{f(d[k])}</span>{arr(d[k], prev[k] if prev else None, hb)}</td>'
    return out
trs = ""; prev = None; dprev = None
NC = len(COLS) + 1
def sigrow(d, k):
    sg = d.get("sig")
    if not sg or not sg.get("code"): return ""
    li = "".join(f"<li>{html.escape(x)}</li>" for x in sg["details"])
    return (f'<tr class="sigd" id="sd{k}" hidden><td colspan="{NC}"><div class="sdb"><b>{SIGL[sg["code"]]}:</b> {html.escape(sg["reason"])}<ul>{li}</ul></div></td></tr>')
for (name, d), k in zip(rows, months):
    d["_id"] = k
    trs += (f'<tr class="mon"><th scope="row"><button type="button" class="ex" aria-expanded="false" aria-controls="g{k}" data-m="{k}">'
            f'<span class="chev" aria-hidden="true">▸</span>{name}</button></th>{cells(d, prev)}</tr>' + sigrow(d, k)); prev = d
    first = dt.date.fromisoformat(k + "-01"); day = first; wprev = None
    while day.month == first.month and day <= NOW.date():
        wstart = day; wend = day
        while wend.weekday() != 6 and (wend + dt.timedelta(1)).month == first.month and wend + dt.timedelta(1) <= NOW.date(): wend += dt.timedelta(1)
        wdays = [wstart + dt.timedelta(i) for i in range((wend - wstart).days + 1)]
        wk = [x.isoformat() for x in wdays]; wid = f"{k}-{wstart.isoformat()}"
        wd = calc(sum(spd.get(x, 0) for x in wk), sum(msd.get(x, 0) for x in wk), sum(rvd.get(x, 0) for x in wk), sum(odd.get(x, 0) for x in wk))
        wlab = wstart.strftime("%-d %b") + (" – " + wend.strftime("%-d %b") if wend != wstart else "")
        trs += (f'<tr class="wk" data-m="{k}" hidden><th scope="row"><button type="button" class="ex" aria-expanded="false" data-w="{wid}">'
                f'<span class="chev" aria-hidden="true">▸</span>{wlab}</button></th>{cells(wd, wprev, True, (DAYB["np"][0] * len(wdays), 0))}</tr>')
        wprev = wd
        for x in wdays:
            ds = x.isoformat(); dd = calc(spd.get(ds, 0), msd.get(ds, 0), rvd.get(ds, 0), odd.get(ds, 0))
            trs += f'<tr class="day" data-m="{k}" data-w="{wid}" hidden><th scope="row">{x.strftime("%a %-d %b")}</th>{cells(dd, dprev, True)}</tr>'
            dprev = dd
        day = wend + dt.timedelta(1)
trs += f'<tr class="tot"><th scope="row">Total</th>{cells(T, None)}</tr>'
RS = rolling_signal(YDAY); c14 = RS["cur"]
G1 = YDAY; G0 = G1 - dt.timedelta(13)
PANEL_LABEL = {"up": "Scale Up", "hold": "Hold Budget", "down": "Scale Down"}[RS["code"]]
if RS["cmp"] and RS["cmp"]["mode"] == "up": MRV = f'{RS["cmp"]["ratio"]:.2f}'; MRL = "marginal return (each extra $1)"
elif RS["cmp"] and RS["cmp"]["mode"] == "down": MRV = "Spend fell"; MRL = "marginal return: see why"
else: MRV = f'${_headroom(c14):.2f}' if c14 and c14["s"] else "—"; MRL = "return per $1 of ads now (spend too steady for the extra-spend test)"
_li = "".join(f"<li>{html.escape(x)}</li>" for x in RS["details"])
cpo14 = (c14["s"] / c14["o"]) if c14["o"] else None
SIGP = f'''<section class="sig {SIGC[RS["code"]]}"><div class="sg"><span class="sgl">Budget signal</span><b>{PANEL_LABEL}</b><p>{html.escape(RS["reason"])}</p></div>
<div class="sgm"><div><b>${c14["cpm"]:.2f}</b><span>cost per click</span></div><div><b>${c14["be"]:.2f}</b><span>break-even per click</span></div><div><b>{c14["conv"]*100:.1f}%</b><span>clicks to orders</span></div><div><b>${(c14["aov"] or 0):,.2f}</b><span>average order</span></div><div><b>{("$%.2f" % cpo14) if cpo14 else "—"}</b><span>cost per order</span></div><div><b>{MRV}</b><span>{MRL}</span></div></div>
<p class="sgn">Last 14 full days, {G0.strftime("%-d %b")} to {G1.strftime("%-d %b")}: ${c14["s"]:,.0f} spend, {int(c14["m"]):,} clicks, {c14["o"]:.0f} tracked orders, ${c14["r"]:,.0f} tracked sales, ${c14["p"]:,.0f} net profit.</p>
<details class="sgn why"><summary>Why this signal</summary><ul>{_li}</ul></details></section>'''
hdr = "".join(f"<th>{l}</th>" for _, l, *_ in COLS)

# page chrome: reuse monthly.py's CSS and script verbatim
DK = "--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17;--gd:#6FD6A6;--bd:#FF8C80"
css = src.split("<style>\n", 1)[1].split("</style></head>", 1)[0].replace("{{{DK}}}", "{" + DK + "}").replace("{{", "{").replace("}}", "}")
js = "<script>" + src.split("</main><script>", 1)[1].split("</script></body></html>", 1)[0].replace("{{", "{").replace("}}", "}") + "</script>"
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Facebook tracked monthly profitability</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
{css}
</style></head><body><main>
<header><div class="hd"><h1>Facebook tracked monthly profitability</h1><p>Tracked Meta sales campaigns against the sales Meta tracks to them. Data to {NOW.strftime("%-d %b %Y")}.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
{SIGP}
<div class="bar"><button type="button" id="all">Expand all</button><button type="button" id="none">Collapse all</button></div>
<div class="wrap"><table><thead><tr><th>Month</th>{hdr}</tr></thead><tbody>{trs}</tbody></table></div>
<section class="notes">
<div class="box"><h2>How it's calculated</h2>
<p><b style="color:var(--ink)">Tracked sales:</b> purchase value Meta records against campaigns with "Tracked" in the name (Non Tracked campaigns are excluded), including GST.</p>
<p><b style="color:var(--ink)">Net profit:</b> tracked sales − GST (1/11 of sales) − product cost (a quarter of sales after GST) − ad spend.</p>
<p><b style="color:var(--ink)">Weekly and daily rows:</b> click a month to see its weeks (Monday to Sunday), then a week to see each day. Daily net profit is green at $33 or more (a monthly $1,000 spread over 30 days), yellow from $0 to $33, red for a loss.</p>
<p><b style="color:var(--ink)">Break-even per click:</b> sales per click × 0.68 (what's left after GST and product cost). A guardrail, not the decision.</p>
<p><b style="color:var(--ink)">Signal:</b> same rules as the non-tracked report, with clicks in place of messages. It compares the last 14 full days with the 14 before (7-day and 28-day windows as checks) and asks whether extra ad spend is still adding profit. Scale Up when each extra $1 returns $1.20 or more of contribution and profit is positive; Hold between $0.90 and $1.20 or when there are under 6 tracked orders; Scale Down under $0.90, or when cost per click is above break-even and the period is making a loss. Click a signal to see why.</p>
<p><b style="color:var(--ink)">Arrows:</b> change on the previous month. Green is better, red is worse, grey is spend.</p>
<p>Starts March 2026. * Month to date. Meta's own purchase tracking can differ from Shopify orders.</p></div>
<div class="box"><h2>Colour bands</h2><table>
<tr><th></th><th><span class="v g"><span class="d"></span>Green</span></th><th><span class="v y"><span class="d"></span>Yellow</span></th><th><span class="v r"><span class="d"></span>Red</span></th></tr>
<tr><td>ROAS</td><td>2.0x or more</td><td>1.47x to 2.0x</td><td>under 1.47x (loss)</td></tr>
<tr><td>Cost per click</td><td>under $0.40</td><td>$0.40 to $0.60</td><td>over $0.60</td></tr>
<tr><td>Sales per click</td><td>$1.20 or more</td><td>$0.80 to $1.20</td><td>under $0.80</td></tr>
<tr><td>Clicks to orders</td><td>2% or more</td><td>1% to 2%</td><td>under 1%</td></tr>
<tr><td>Net profit</td><td>$1,000 or more</td><td>$0 to $1,000</td><td>loss</td></tr>
<tr><td>Net profit per click</td><td>$0.30 or more</td><td>$0 to $0.30</td><td>loss</td></tr>
</table></div></section>
</main>{js}</body></html>'''
sys.path.insert(0, HERE)
import tile_periods as _tp
page = page.replace("</body>", _tp.tag(_tp.periods(NOW.date(), spd, rvd)) + "</body>", 1)
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
