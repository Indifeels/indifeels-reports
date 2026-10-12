sp, ms, rv, od = {}, {}, {}, {}
mrm = {}
for d in spd:
    k = d[:7]; sp[k] = sp.get(k, 0) + spd[d]; ms[k] = ms.get(k, 0) + msd[d]
    rv[k] = rv.get(k, 0) + rvd.get(d, 0); od[k] = od.get(k, 0) + odd.get(d, 0); mrm[k] = mrm.get(k, 0) + mrd.get(d, 0)
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
def att(a, b):
    """Share of the money both sources agree on: smaller / larger, as a percent."""
    if not HAVE_SHOP or (not a and not b): return None
    return min(a, b) / max(a, b) * 100
def calc(s, m, r, o, mr=0, sh=0):
    p = r / 1.1 * 0.75 - s
    return dict(mr=mr, sh=sh if HAVE_SHOP else None, att=att(mr, sh), s=s, r=r, roas=dv(r, s), spm=dv(s, m), rpm=dv(r, m), mto=dv(o * 100, m), np=p, npm=dv(p, m),
                o=o, m=m, cpo=dv(s, o), be=dv(r * 0.75 / 1.1, m), sig=None)
rows = [(dt.date.fromisoformat(k + "-01").strftime("%b %Y") + ("*" if k == NOW.strftime("%Y-%m") else ""), calc(sp[k], ms[k], rv.get(k, 0), od.get(k, 0), mrm.get(k, 0), shm.get(k, 0))) for k in months]
for (_n, _d), _k in zip(rows, months): _d["sig"] = month_sig(_k)
T = calc(sum(sp[k] for k in months), sum(ms[k] for k in months), sum(rv.get(k, 0) for k in months), sum(od.get(k, 0) for k in months), sum(mrm.get(k, 0) for k in months), sum(shm.get(k, 0) for k in months))
def m0(v): return ("−" if v < 0 else "") + f"${abs(v):,.0f}"
def m2(v): return ("−" if v < 0 else "") + f"${abs(v):,.2f}"
COLS = [("s", "Spend", lambda v: f"${v:,.0f}", None, None),
        ("m", "Clicks", lambda v: f"{int(v):,}", None, True),
        ("spm", "Cost per click", lambda v: f"${v:.2f}", (0.40, 0.60), False),
        ("mr", "Meta tracked sales", lambda v: f"${v:,.0f}", None, True),
        ("sh", "Shopify FB web sales", lambda v: f"${v:,.0f}", None, True),
        ("att", "Attribution %", lambda v: f"{v:.0f}%", (90, 70), True),
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
    return (f'<tr class="sigd" id="sd{k}{SFX}" hidden><td colspan="{NC}"><div class="sdb"><b>{SIGL[sg["code"]]}:</b> {html.escape(sg["reason"])}<ul>{li}</ul></div></td></tr>')
for (name, d), k in zip(rows, months):
    d["_id"] = k + SFX
    trs += (f'<tr class="mon"><th scope="row"><button type="button" class="ex" aria-expanded="false" aria-controls="g{k}{SFX}" data-m="{k}{SFX}">'
            f'<span class="chev" aria-hidden="true">▸</span>{name}</button></th>{cells(d, prev)}</tr>' + sigrow(d, k)); prev = d
    first = dt.date.fromisoformat(k + "-01"); day = first; wprev = None
    while day.month == first.month and day <= NOW.date():
        wstart = day; wend = day
        while wend.weekday() != 6 and (wend + dt.timedelta(1)).month == first.month and wend + dt.timedelta(1) <= NOW.date(): wend += dt.timedelta(1)
        wdays = [wstart + dt.timedelta(i) for i in range((wend - wstart).days + 1)]
        wk = [x.isoformat() for x in wdays]; wid = f"{k}{SFX}-{wstart.isoformat()}"
        wd = calc(sum(spd.get(x, 0) for x in wk), sum(msd.get(x, 0) for x in wk), sum(rvd.get(x, 0) for x in wk), sum(odd.get(x, 0) for x in wk), sum(mrd.get(x, 0) for x in wk), sum(shd.get(x, 0) for x in wk))
        wlab = wstart.strftime("%-d %b") + (" – " + wend.strftime("%-d %b") if wend != wstart else "")
        trs += (f'<tr class="wk" data-m="{k}{SFX}" hidden><th scope="row"><button type="button" class="ex" aria-expanded="false" data-w="{wid}">'
                f'<span class="chev" aria-hidden="true">▸</span>{wlab}</button></th>{cells(wd, wprev, True, (DAYB["np"][0] * len(wdays), 0))}</tr>')
        wprev = wd
        for x in wdays:
            ds = x.isoformat(); dd = calc(spd.get(ds, 0), msd.get(ds, 0), rvd.get(ds, 0), odd.get(ds, 0), mrd.get(ds, 0), shd.get(ds, 0))
            trs += f'<tr class="day" data-m="{k}{SFX}" data-w="{wid}" hidden><th scope="row">{x.strftime("%a %-d %b")}</th>{cells(dd, dprev, True)}</tr>'
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
