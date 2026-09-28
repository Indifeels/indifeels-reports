import json,datetime as dt,html,sys
from zoneinfo import ZoneInfo
TZ=ZoneInfo("Australia/Sydney")
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'build.py')).read().split('def cpm(s,m)')[0])
sp={};ms={}
for c,days in by.items():
    for d,(s,m) in days.items(): k=d[:7]; sp[k]=sp.get(k,0)+s; ms[k]=ms.get(k,0)+m
spd={};msd={}
for c,days in by.items():
    for d,(s_,m_) in days.items(): spd[d]=spd.get(d,0)+s_; msd[d]=msd.get(d,0)+m_
FB={"FB/IG PAGE MSGS MEL - SALE","FB WHATSAPP MSGS MEL - SALE"}
rv={};od={};rvd={};odd={}
for n in ordmap.values():
    if n["cancelledAt"] or (n["m"] or {}).get("value") not in FB: continue
    k=dt.datetime.fromisoformat(n["processedAt"].replace("Z","+00:00")).astimezone(TZ).strftime("%Y-%m")
    a=float(n["t"]["shopMoney"]["amount"]); dd=dt.datetime.fromisoformat(n["processedAt"].replace("Z","+00:00")).astimezone(TZ).date().isoformat()
    rv[k]=rv.get(k,0)+a; od[k]=od.get(k,0)+1; rvd[dd]=rvd.get(dd,0)+a; odd[dd]=odd.get(dd,0)+1
months=[k for k in sorted(sp) if k>="2026-03"]
TRACK_START=dt.date.fromisoformat(min(rvd)).replace(day=1)
# ===== SIGNAL ENGINE (profit-maximisation) — BEGIN =====
# Inputs expected in scope: spd, msd, rvd, odd  (dicts keyed "YYYY-MM-DD": spend, messages, FB revenue, FB orders)
#                           TRACK_START (date sales attribution began)
import datetime as _dt
CONTRIB = 0.75 / 1.1          # 0.681818: revenue left after GST (1/11) and product cost (25% of ex-GST)
SCALE_MCR, HOLD_MCR = 1.20, 0.90
MIN_SPEND_CHANGE = 0.10       # below 10% spend change = insufficient change
MIN_ORDERS = 6                # fewer attributed orders in a primary window = low volume
HEADROOM_ACR = 1.50           # when marginal return can't be measured: scale if each $1 of ads currently returns >= $1.50 contribution
                              # (marginal returns sit below average returns, so this leaves room to stay above the 1.20 scale line)

def _win(end, n):
    start = end - _dt.timedelta(n - 1)
    if start < TRACK_START:
        return None
    ks = [(start + _dt.timedelta(i)).isoformat() for i in range(n)]
    s = sum(spd.get(k, 0) for k in ks); m = sum(msd.get(k, 0) for k in ks)
    r = sum(rvd.get(k, 0) for k in ks); o = sum(odd.get(k, 0) for k in ks)
    c = r * CONTRIB
    return dict(s=s, m=m, r=r, o=o, c=c, p=c - s, days=n,
                cpm=s / m if m else None, rpm=r / m if m else None,
                conv=o / m if m else None, aov=r / o if o else None,
                be=(r * CONTRIB / m) if m else None)

def _per_day(w):
    return {k: (w[k] / w["days"] if k in ("s", "m", "r", "o", "c", "p") else w[k]) for k in w}

def _compare(cur, prev):
    """Compare two windows on a per-day basis (so unequal lengths are comparable)."""
    if not cur or not prev or prev["s"] <= 0:
        return None
    a, b = _per_day(cur), _per_day(prev)
    dS = a["s"] - b["s"]; dR = a["r"] - b["r"]; dC = a["c"] - b["c"]; dP = a["p"] - b["p"]
    chg = dS / b["s"]
    res = dict(cur=cur, prev=prev, dS=dS, dR=dR, dC=dC, dP=dP, spend_chg=chg, mode=None, ratio=None, verdict=None)
    if abs(chg) < MIN_SPEND_CHANGE:
        res["mode"] = "flat"
    elif dS > 0:
        res["mode"] = "up"; res["ratio"] = dC / dS          # MCR: extra contribution per extra $1
        res["verdict"] = "up" if res["ratio"] >= SCALE_MCR else ("down" if res["ratio"] < HOLD_MCR else "neutral")
    else:
        res["mode"] = "down"; res["ratio"] = dC / dS        # contribution lost per $1 saved (both negative -> positive)
        # cutting spend lost more contribution than it saved -> account was under-scaled (evidence for more spend)
        res["verdict"] = "up" if res["ratio"] >= SCALE_MCR else ("down" if res["ratio"] < HOLD_MCR else "neutral")
    return res

def _pct(a, b):
    if a is None or b in (None, 0): return None
    return (a - b) / abs(b) * 100

def _f(v, kind):
    if v is None: return "n/a"
    if kind == "$": return ("−" if v < 0 else "") + f"${abs(v):,.0f}"
    if kind == "$2": return ("−" if v < 0 else "") + f"${abs(v):,.2f}"
    if kind == "%": return ("+" if v >= 0 else "−") + f"{abs(v):.0f}%"
    if kind == "x": return f"{v:.2f}"
    return str(v)

def _wdesc(nm, w):
    if not w:
        return f"{nm}: not available (needs tracked sales in both periods)."
    sc = _f(w["spend_chg"] * 100, "%")
    if w["mode"] == "flat":
        return f"{nm}: spend {sc}, under 10% change, so marginal return isn't measured (insufficient change)."
    r = w["ratio"]
    if w["mode"] == "up":
        if r < 0:
            return f"{nm}: spend {sc} but contribution fell, so the extra spend added no contribution (marginal return below zero)."
        return f"{nm}: spend {sc}, Marginal Contribution Return {r:.2f} (each extra $1 of ads produced ${r:.2f} of contribution)."
    if r < 0:
        return f"{nm}: spend {sc} and contribution rose, so the cut improved profit."
    return f"{nm}: spend {sc}; each $1 saved lost ${r:.2f} of contribution" + (" (the cut reduced profit)." if r >= 1 else " (the cut improved profit).")

def _headroom(cur):
    """Average contribution return (contribution per $1 of ads) for the period, used when marginal return can't be measured."""
    return cur["c"] / cur["s"] if cur and cur["s"] > 0 else None

def _headroom_text(cur, acr):
    return (f"Each $1 of ads currently returns ${acr:.2f} of contribution (cost per message ${cur['cpm']:.2f} vs break-even ${cur['be']:.2f})")

def signal_for(primary, recent=None, baseline=None, primary_label="Last 14 days", cur_only=None):
    """primary/recent/baseline are _compare() results. Returns dict(code,label,reason,details,metrics)."""
    P = primary
    cur = P["cur"] if P else None
    out = dict(code="hold", label="Hold Budget", reason="", details=[], cur=cur, cmp=P,
               mcr7=recent["ratio"] if recent and recent["mode"] == "up" else None,
               mcr14=P["ratio"] if P and P["mode"] == "up" else None,
               mcr28=baseline["ratio"] if baseline and baseline["mode"] == "up" else None)
    if not P:
        c0 = cur_only
        if not c0 or not c0["s"] or not c0["m"]:
            out.update(code=None, label="—", reason="No data for this period.")
            return out
        acr = _headroom(c0); out["cur"] = c0
        if c0["cpm"] is not None and c0["be"] is not None and c0["cpm"] > c0["be"] and c0["p"] <= 0:
            code, why = "down", "Cost per message is above break-even and the period is making a loss. Reduce budget and reassess."
        elif c0["o"] < MIN_ORDERS:
            code, why = "hold", f"Only {c0['o']} attributed orders, too few to justify a budget change."
        elif acr >= HEADROOM_ACR and c0["p"] > 0:
            code, why = "up", f"No earlier period with tracked sales to compare against. {_headroom_text(c0, acr)}, so there is clear room to scale. Raise budget about 20% and re-check after 14 days."
        else:
            code, why = "hold", f"No earlier period with tracked sales to compare against. {_headroom_text(c0, acr)}; not enough headroom to scale confidently."
        out.update(code=code, label={"up": "Scale Up", "hold": "Hold Budget", "down": "Scale Down"}[code], reason=why,
                   details=["No comparable earlier period with tracked sales, so marginal return can't be measured.",
                            f"Average contribution return: ${acr:.2f} per $1 of ads. Scale Up needs ${HEADROOM_ACR:.2f} or more.",
                            f"Period: spend ${c0['s']:,.0f}, revenue ${c0['r']:,.0f}, {c0['o']} orders, net profit ${c0['p']:,.0f}.",
                            f"Guardrail: cost per message ${c0['cpm']:.2f} vs break-even ${c0['be']:.2f}."])
        return out
    prev = P["prev"]
    # ---------- diagnostics ----------
    d_msgs = _pct(cur["m"] / cur["days"], prev["m"] / prev["days"])
    d_conv = _pct(cur["conv"], prev["conv"]); d_rpm = _pct(cur["rpm"], prev["rpm"])
    d_cpm = _pct(cur["cpm"], prev["cpm"]); d_rev = _pct(cur["r"] / cur["days"], prev["r"] / prev["days"])
    d_c = _pct(cur["c"] / cur["days"], prev["c"] / prev["days"])
    d_p = cur["p"] / cur["days"] - prev["p"] / prev["days"]
    lowvol = cur["o"] < MIN_ORDERS
    code = None; why = ""
    PL = "this month" if primary_label == "This month" else "the last 14 days"
    # 1. hard safety override
    if cur["cpm"] is not None and cur["be"] is not None and cur["cpm"] > cur["be"] and cur["p"] <= 0:
        code = "down"; why = "Cost per message is above break-even and the period is making a loss. Reduce budget and reassess."
    elif lowvol:
        code = "hold"; why = f"Only {cur['o']} attributed orders in this period, too few to justify a budget change. Maintain budget while more data accumulates."
    elif P["mode"] == "flat":
        acr = _headroom(cur)
        if acr is not None and acr >= HEADROOM_ACR and cur["p"] > 0:
            code = "up"
            why = (f"Spend has been steady ({_f(P['spend_chg']*100,'%')}), so the extra-spend test can't be read yet. {_headroom_text(cur, acr)}, "
                   "so there is clear room to scale. Raise budget about 20% and re-check after 14 days.")
        else:
            code = "hold"
            why = (f"Spend has been steady ({_f(P['spend_chg']*100,'%')}), so the extra-spend test can't be read yet. {_headroom_text(cur, acr)}; "
                   + ("profitable but without enough headroom to scale confidently. Maintain budget and work on conversion." if cur["p"] > 0 else "profit is thin. Maintain budget and work on conversion."))
    elif P["mode"] == "up":
        mcr = P["ratio"]
        r_v = recent["verdict"] if recent and recent["mode"] != "flat" else None
        b_v = baseline["verdict"] if baseline and baseline["mode"] != "flat" else None
        if mcr >= SCALE_MCR and cur["p"] > 0:
            if r_v == "down" and b_v == "down":
                acr = _headroom(cur)
                if acr >= HEADROOM_ACR:
                    code = "up"; why = f"Extra spend paid off over {PL}, and although the 7 and 28-day checks disagree, {_headroom_text(cur, acr).lower()}. Scale carefully and re-check after 14 days."
                else:
                    code = "hold"; why = f"Extra spend paid off over {PL}, but both the last 7 days and the 28-day baseline point the other way. Maintain budget until the trend is consistent."
            else:
                code = "up"
                strong = mcr >= 1.5 or r_v == "up" or b_v == "up"
                if d_cpm is not None and d_cpm > 5 and d_rpm is not None and d_rpm > d_cpm:
                    why = "Acquisition cost increased, but customer value increased faster, producing higher total profit."
                elif d_msgs is not None and abs(d_msgs) < 10 and d_rpm is not None and d_rpm > 10:
                    why = "Stronger customer value is increasing profit despite limited message growth."
                else:
                    why = "Additional spend is still increasing total profit. Marginal contribution remains " + ("strong." if strong else "positive.")
        elif mcr < HOLD_MCR:
            if r_v == "up":
                code = "hold"; why = f"Extra spend over {PL} returned less than it cost, but the last 7 days show a strong recovery. Maintain budget rather than cutting on short-term noise."
            else:
                code = "down"
                if d_cpm is not None and d_cpm < 0 and d_rev is not None and d_rev < 0:
                    why = "Cheaper messages are not translating into sufficient revenue. Recent additional spend is producing less contribution than it costs."
                elif d_msgs is not None and d_msgs > 10 and d_conv is not None and d_conv < -10:
                    why = "Additional spend is generating more conversations, but weaker conversion is preventing those messages from becoming profitable revenue."
                else:
                    why = "Recent additional spend is producing less contribution than it costs. Reduce budget and reassess."
        else:
            code = "hold"; why = "Current spend is profitable, but marginal profit is flattening. Maintain budget while more data accumulates."
    else:  # spend fell
        lost = P["ratio"]
        if P["verdict"] == "up" and cur["p"] > 0:
            r_v = recent["verdict"] if recent and recent["mode"] != "flat" else None
            if r_v == "down" and _headroom(cur) < HEADROOM_ACR:
                code = "hold"; why = f"Lower spend cut profit over {PL}, but the last 7 days disagree. Maintain budget until the trend is consistent."
            else:
                code = "up"; why = f"Spend fell {_f(-P['spend_chg']*100,'%').lstrip('+')} and profit fell with it: each $1 saved cost ${lost:.2f} of contribution. The account looks under-scaled; restoring spend should increase total profit."
        elif P["verdict"] == "down":
            code = "hold"; why = "Spend fell and profit held up or improved, so the earlier higher spend was probably inefficient. Keep the lower budget."
        else:
            code = "hold"; why = "Spend fell and profit moved roughly in line. Maintain budget while more data accumulates."
    out["code"] = code
    out["label"] = {"up": "Scale Up", "hold": "Hold Budget", "down": "Scale Down"}[code]
    out["reason"] = why
    # ---------- details (hidden by default) ----------
    det = []
    det.append(f"{primary_label} vs the previous comparable period (per-day basis):")
    det.append(f"Spend {_f(P['spend_chg']*100,'%')}, revenue {_f(d_rev,'%')}, contribution {_f(d_c,'%')}, change in net profit {_f(d_p*cur['days'],'$')}.")
    det.append(_wdesc("Primary", P))
    for nm, w in (("7-day", recent), ("28-day", baseline)):
        det.append(_wdesc(nm, w))
    det.append(f"Revenue per message {_f(d_rpm,'%')}, messages to orders {_f(d_conv,'%')}, messages per day {_f(d_msgs,'%')}, cost per message {_f(d_cpm,'%')}.")
    _a = _headroom(cur)
    if _a is not None: det.append(f"Average contribution return: ${_a:.2f} per $1 of ads (used when the extra-spend test can't be read; Scale Up needs ${HEADROOM_ACR:.2f}+).")
    det.append(f"Guardrail: cost per message {_f(cur['cpm'],'$2')} vs break-even {_f(cur['be'],'$2')}; period net profit {_f(cur['p'],'$')}.")
    out["details"] = det
    return out

def rolling_signal(end):
    """Signal using 14-day primary, 7-day recent and 28-day baseline windows ending on `end` (a complete day)."""
    cmp = {}
    for n in (7, 14, 28):
        cur = _win(end, n); prev = _win(end - _dt.timedelta(n), n)
        cmp[n] = _compare(cur, prev)
    return signal_for(cmp[14], cmp[7], cmp[28], "Last 14 days", cur_only=_win(end, 14))

def month_signal(mstart, mend, pstart, pend):
    """Completed month vs previous month on a per-day basis, with 7/28-day windows ending at month end."""
    def rng(a, b):
        n = (b - a).days + 1
        if a < TRACK_START: return None
        return _win(b, n)
    prim = _compare(rng(mstart, mend), rng(pstart, pend))
    cmp7 = _compare(_win(mend, 7), _win(mend - _dt.timedelta(7), 7))
    cmp28 = _compare(_win(mend, 28), _win(mend - _dt.timedelta(28), 28))
    return signal_for(prim, cmp7, cmp28, "This month", cur_only=_win(mend, (mend - mstart).days + 1))
# ===== SIGNAL ENGINE — END =====

import calendar as _cal
YDAY=NOW.date()-dt.timedelta(1)
def month_sig(k):
    ms_=dt.date.fromisoformat(k+"-01"); me_=ms_.replace(day=_cal.monthrange(ms_.year,ms_.month)[1])
    if me_>=NOW.date(): return rolling_signal(YDAY)          # current partial month: rolling 14-day signal
    pe_=ms_-dt.timedelta(1); ps_=pe_.replace(day=1)
    return month_signal(ms_,me_,ps_,pe_)
def dv(a,b): return a/b if b else None
def calc(s,m,r,o):
    p=r/1.1*0.75-s
    be=dv(r*0.75/1.1,m)
    return dict(s=s,r=r,roas=dv(r,s),spm=dv(s,m),rpm=dv(r,m),mto=dv(o*100,m),np=p,npm=dv(p,m),o=o,m=m,be=be,sig=None)
rows=[(dt.date.fromisoformat(k+"-01").strftime("%b %Y")+("*" if k==NOW.strftime("%Y-%m") else ""),calc(sp[k],ms[k],rv.get(k,0),od.get(k,0))) for k in months]
for (_n,_d),_k in zip(rows,months): _d["sig"]=month_sig(_k)
T=calc(sum(sp[k] for k in months),sum(ms[k] for k in months),sum(rv.get(k,0) for k in months),sum(od.get(k,0) for k in months))
# key, label, fmt, bands(g,y) higher-better?, arrow sense
def m0(v): return ("−" if v<0 else "")+f"${abs(v):,.0f}"
def m2(v): return ("−" if v<0 else "")+f"${abs(v):,.2f}"
COLS=[("s","Spend",lambda v:f"${v:,.0f}",None,None),
 ("m","Messages",lambda v:f"{int(v):,}",None,True),
 ("spm","Spend per message",lambda v:f"${v:.2f}",(4.5,6),False),
 ("r","Revenue",lambda v:f"${v:,.0f}",None,True),
 ("rpm","Revenue per message",lambda v:f"${v:.2f}",(10,6),True),
 ("roas","ROAS",lambda v:f"{v:.2f}x",(2.5,1.4727),True),
 ("mto","Messages to orders",lambda v:f"{v:.1f}%",(7,5),True),
 ("npm","Net profit per message",m2,(3,1),True),
 ("np","Net profit",m0,(2000,0),True),
 ("be","Break-even per message",lambda v:f"${v:.2f}",None,True),
 ("sig","Signal",None,None,None)]
def band(v,b,hb):
    if not b or v is None: return ""
    g,y=b
    if hb: return "g" if v>=g else "y" if v>=y else "r"
    return "g" if v<g else "y" if v<=y else "r"
def arr(v,pv,sense):
    if pv is None or v is None or round(v,4)==round(pv,4): return '<i class="a"></i>'
    up=v>pv; cls="n" if sense is None else ("gd" if up==sense else "bd")
    return f'<i class="a {cls}" title="{"Up" if up else "Down"} on previous month">{"▲" if up else "▼"}</i>'
DAYB={"np":(67,0)}
SIGL={"up":"Scale Up","hold":"Hold","down":"Scale Down"}; SIGC={"up":"scale","hold":"hold","down":"cut"}
def cells(d,prev,day=False):
    out=""
    for k,_,f,b,sense in COLS:
        if k=="sig":
            sg=d.get("sig")
            if sg and sg.get("code") and not day:
                out+=f'<td><button type="button" class="sgc {SIGC[sg["code"]]}" aria-expanded="false" data-sd="{d.get("_id","")}" title="Show why">{SIGL[sg["code"]]} <span aria-hidden="true">ⓘ</span></button></td>'
            elif sg and not day:
                out+=f'<td><span class="v none" title="{html.escape(sg["reason"])}">—</span></td>'
            else: out+='<td><span class="v none">—</span></td>'
            continue
        if k=="be" and day:
            out+='<td><span class="v none">—</span></td>'; continue
        if day and k in DAYB: b=DAYB[k]
        if d[k] is None:
            out+='<td><span class="v none">'+("No msgs" if k in ("spm","rpm","mto","npm") and d["s"] else "—")+'</span><i class="a"></i></td>'; continue
        bd=band(d[k],b,COLS[[c[0] for c in COLS].index(k)][4] if k!="spm" else False)
        dot=f'<span class="d {bd}"></span>' if bd else ""
        out+=f'<td><span class="v {bd}">{dot}{f(d[k])}</span>{arr(d[k],prev[k] if prev else None,sense if k!="spm" else False)}</td>'
    return out
trs=""; prev=None; dprev=None
NC=len(COLS)+1
def sigrow(d,k):
    sg=d.get("sig")
    if not sg or not sg.get("code"): return ""
    li="".join(f"<li>{html.escape(x)}</li>" for x in sg["details"])
    return (f'<tr class="sigd" id="sd{k}" hidden><td colspan="{NC}"><div class="sdb"><b>{SIGL[sg["code"]]}:</b> {html.escape(sg["reason"])}'
            f'<ul>{li}</ul></div></td></tr>')
for (name,d),k in zip(rows,months):
    d["_id"]=k
    trs+=(f'<tr class="mon"><th scope="row"><button type="button" class="ex" aria-expanded="false" aria-controls="g{k}" data-m="{k}">'
          f'<span class="chev" aria-hidden="true">▸</span>{name}</button></th>{cells(d,prev)}</tr>'+sigrow(d,k)); prev=d
    first=dt.date.fromisoformat(k+"-01"); day=first
    while day.month==first.month and day<=NOW.date():
        ds=day.isoformat(); dd=calc(spd.get(ds,0),msd.get(ds,0),rvd.get(ds,0),odd.get(ds,0))
        trs+=f'<tr class="day" data-m="{k}" hidden><th scope="row">{day.strftime("%a %-d %b")}</th>{cells(dd,dprev,True)}</tr>'
        dprev=dd; day+=dt.timedelta(1)
trs+=f'<tr class="tot"><th scope="row">Total</th>{cells(T,None)}</tr>'
RS=rolling_signal(YDAY); c14=RS["cur"]
G1=YDAY; G0=G1-dt.timedelta(13)
PANEL_LABEL={"up":"Scale Up","hold":"Hold Budget","down":"Scale Down"}[RS["code"]]
if RS["cmp"] and RS["cmp"]["mode"]=="up": MRV=f'{RS["cmp"]["ratio"]:.2f}'; MRL="marginal return (each extra $1)"
elif RS["cmp"] and RS["cmp"]["mode"]=="down": MRV="Spend fell"; MRL="marginal return: see why"
else: MRV=f'${_headroom(c14):.2f}' if c14 and c14["s"] else "—"; MRL="return per $1 of ads now (spend too steady for the extra-spend test)"
_li="".join(f"<li>{html.escape(x)}</li>" for x in RS["details"])
SIGP=f'''<section class="sig {SIGC[RS["code"]]}"><div class="sg"><span class="sgl">Budget signal</span><b>{PANEL_LABEL}</b><p>{html.escape(RS["reason"])}</p></div>
<div class="sgm"><div><b>${c14["cpm"]:.2f}</b><span>cost per message</span></div><div><b>${c14["be"]:.2f}</b><span>break-even per message</span></div><div><b>{c14["conv"]*100:.1f}%</b><span>messages to orders</span></div><div><b>${(c14["aov"] or 0):,.2f}</b><span>average order</span></div><div><b>{MRV}</b><span>{MRL}</span></div></div>
<p class="sgn">Last 14 full days, {G0.strftime("%-d %b")} to {G1.strftime("%-d %b")}: ${c14["s"]:,.0f} spend, {int(c14["m"]):,} messages, {c14["o"]} FB orders, ${c14["r"]:,.0f} revenue, ${c14["p"]:,.0f} net profit.</p>
<details class="sgn why"><summary>Why this signal</summary><ul>{_li}</ul></details></section>'''
hdr="".join(f"<th>{l}</th>" for _,l,*_ in COLS)
DK="--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--y:#F2C85B;--yb:#362A0E;--r:#FF8C80;--rb:#3D1A17;--gd:#6FD6A6;--bd:#FF8C80"
page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Monthly profitability report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Figtree:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#F6F7F9;--card:#FFF;--ink:#101828;--muted:#5A6272;--line:#D9DEE6;--sub:#EEF1F5;--mari:#E8A317;--g:#17694A;--gb:#D5F2E3;--y:#7A4E00;--yb:#FFEDBF;--r:#A8231B;--rb:#FFE0DC;--gd:#17694A;--bd:#C0392B}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{DK}}}}}
:root[data-theme="dark"]{{{DK}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.45 Figtree,system-ui,-apple-system,"Segoe UI",sans-serif;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
main{{max-width:1500px;margin:0 auto;padding:24px 16px 48px}}
header{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:18px}}
.hd{{border-left:6px solid var(--mari);padding-left:14px}}
h1{{font:700 clamp(24px,4vw,34px)/1.1 "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 4px}}
.hd p{{margin:0;color:var(--muted)}}
.tg{{flex:none;font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:7px 14px;cursor:pointer}}
.wrap{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{white-space:nowrap}}
thead th{{white-space:normal;vertical-align:bottom;min-width:84px;font-size:13px;font-weight:600;color:var(--muted);text-align:right;padding:12px 8px 10px;border-bottom:1px solid var(--line)}}
thead th:first-child{{text-align:left}}
tbody th{{text-align:left;font-weight:600;padding:11px 12px;position:sticky;left:0;background:var(--card);z-index:1}}
td{{text-align:right;padding:10px 8px}}
tbody tr+tr{{border-top:1px solid var(--line)}}
tr.tot th,tr.tot td{{background:var(--sub);font-weight:700;border-top:2px solid var(--line)}}
.v{{display:inline-flex;align-items:center;gap:5px;padding:2px 7px;border-radius:6px;font-weight:600}}
.v.g{{background:var(--gb);color:var(--g)}}.v.y{{background:var(--yb);color:var(--y)}}.v.r{{background:var(--rb);color:var(--r)}}
.d{{width:7px;height:7px;border-radius:50%;flex:none;background:currentColor}}
.a{{display:inline-block;width:12px;margin-left:5px;font-style:normal;font-size:10px;text-align:center;vertical-align:1px}}
.a.gd{{color:var(--gd)}}.a.bd{{color:var(--bd)}}.a.n{{color:var(--muted)}}
.sig{{display:grid;grid-template-columns:minmax(220px,1fr) 3fr;gap:10px 20px;align-items:center;background:var(--card);border:1px solid var(--line);border-left:6px solid var(--sc);border-radius:12px;padding:14px 16px;margin-bottom:14px}}
.sig.scale{{--sc:var(--g)}}.sig.hold{{--sc:var(--y)}}.sig.cut{{--sc:var(--r)}}
.sgl{{display:block;font-size:12.5px;color:var(--muted);font-weight:600}}
.sg b{{display:block;font:700 22px/1.2 "Bricolage Grotesque",Figtree,sans-serif;color:var(--sc)}}
.sg p{{margin:4px 0 0;font-size:13px;color:var(--muted)}}
.sgm{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
.sgm b{{display:block;font:700 19px/1.2 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums}}.sgm span{{font-size:12.5px;color:var(--muted)}}
.sgn{{grid-column:1/-1;margin:0;font-size:12.5px;color:var(--muted)}}
@media (max-width:700px){{.sig{{grid-template-columns:1fr}}}}
.sgc{{display:inline-block;padding:2px 9px;border-radius:99px;font:700 13px Figtree,sans-serif;border:0;cursor:pointer;white-space:nowrap}}
.sgc span{{font-weight:400;opacity:.7}}.sgc:focus-visible{{outline:2px solid var(--mari)}}
tr.sigd td{{background:var(--sub);text-align:left;white-space:normal;padding:10px 16px}}
.sdb{{max-width:900px;font-size:13.5px}}.sdb ul,.why ul{{margin:6px 0 0;padding-left:18px}}.sdb li,.why li{{margin:2px 0;color:var(--muted)}}
.why summary{{cursor:pointer;font-weight:600;color:var(--ink)}}
.sgc.scale{{background:var(--gb);color:var(--g)}}.sgc.hold{{background:var(--yb);color:var(--y)}}.sgc.cut{{background:var(--rb);color:var(--r)}}
tr.mon .ex{{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:8px;font-weight:700;border-radius:6px;padding:2px 4px;margin-left:-4px}}
tr.mon .ex:focus-visible{{outline:2px solid var(--mari)}}
.chev{{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}}
.ex[aria-expanded="true"] .chev{{transform:rotate(90deg)}}
tr.mon:hover th,tr.mon:hover td{{background:var(--sub)}}
tr.day th,tr.day td{{background:var(--bg);font-size:13.5px;padding-top:6px;padding-bottom:6px}}
tr.day th{{font-weight:500;color:var(--muted);padding-left:34px}}
tr.day .v{{font-weight:600}}
.v.none{{color:var(--muted);font-weight:500}}
.bar{{display:flex;gap:8px;margin:0 0 10px}}
.bar button{{font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:6px 12px;cursor:pointer}}
@media (prefers-reduced-motion:reduce){{.chev{{transition:none}}}}
.notes{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:12px;margin-top:14px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;font-size:13.5px}}
.box h2{{font:700 16px "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 8px}}
.box table td,.box table th{{white-space:normal;padding:4px 6px;text-align:left;font-size:13px;border:0}}
.box p{{margin:0 0 6px;color:var(--muted)}}
</style></head><body><main>
<header><div class="hd"><h1>Monthly profitability report</h1><p>Non-tracked Meta messaging campaigns against FB-attributed Shopify sales. Data to {NOW.strftime("%-d %b %Y")}.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
{SIGP}
<div class="bar"><button type="button" id="all">Expand all</button><button type="button" id="none">Collapse all</button></div>
<div class="wrap"><table><thead><tr><th>Month</th>{hdr}</tr></thead><tbody>{trs}</tbody></table></div>
<section class="notes">
<div class="box"><h2>How it's calculated</h2>
<p><b style="color:var(--ink)">Revenue:</b> Shopify orders with order source FB/IG page messages or WhatsApp messages, including GST, after refunds, cancelled orders excluded.</p>
<p><b style="color:var(--ink)">Net profit:</b> revenue − GST (1/11 of revenue) − product cost (a quarter of revenue after GST) − ad spend. What's left at the end.</p>
<p><b style="color:var(--ink)">Daily rows:</b> click a month to see each day. Arrows on day rows compare with the previous day. Daily net profit is green at $67 or more (a monthly $2,000 spread over 30 days), yellow from $0 to $67, red for a loss.</p>
<p><b style="color:var(--ink)">Break-even per message:</b> revenue per message × 0.68 (what's left after GST and product cost). A safety guardrail, not the decision.</p>
<p><b style="color:var(--ink)">Signal:</b> aims for the highest total net profit. It compares the last 14 full days with the 14 before (7-day and 28-day windows as checks) and asks whether extra ad spend is still adding profit. Scale Up when each extra $1 of spend returns $1.20 or more of contribution and profit is positive; Hold between $0.90 and $1.20, or when volume is too small (under 6 orders); Scale Down under $0.90, or whenever cost per message is above break-even and the period is making a loss. When spend barely changed (under 10%) or there's no earlier period to compare with, the extra-spend test can't be read, so the signal uses the current return instead: Scale Up if each $1 of ads returns $1.50 or more of contribution (cost per message at or under about two-thirds of break-even), otherwise Hold. Past months compare with the previous month per day; the current month uses the rolling 14-day signal. Click a signal to see why.</p>
<p><b style="color:var(--ink)">Arrows:</b> change on the previous month. Green is better, red is worse, grey is spend.</p>
<p>Starts March 2026, when order sources began being recorded. * Month to date.</p></div>
<div class="box"><h2>Colour bands</h2><table>
<tr><th></th><th><span class="v g"><span class="d"></span>Green</span></th><th><span class="v y"><span class="d"></span>Yellow</span></th><th><span class="v r"><span class="d"></span>Red</span></th></tr>
<tr><td>ROAS</td><td>2.5x or more</td><td>1.47x to 2.5x</td><td>under 1.47x (loss)</td></tr>
<tr><td>Spend per message</td><td>under $4.50</td><td>$4.50 to $6</td><td>over $6</td></tr>
<tr><td>Revenue per message</td><td>$10 or more</td><td>$6 to $10</td><td>under $6</td></tr>
<tr><td>Messages to orders</td><td>7% or more</td><td>5% to 7%</td><td>under 5%</td></tr>
<tr><td>Net profit</td><td>$2,000 or more</td><td>$0 to $2,000</td><td>loss</td></tr>
<tr><td>Net profit per message</td><td>$3 or more</td><td>$1 to $3</td><td>under $1</td></tr>
</table></div></section>
</main><script>
(function(){{function set(b,o){{b.setAttribute('aria-expanded',o);document.querySelectorAll('tr.day[data-m="'+b.dataset.m+'"]').forEach(function(r){{r.hidden=!o}})}}
var bs=document.querySelectorAll('tr.mon .ex');bs.forEach(function(b){{b.addEventListener('click',function(){{set(b,b.getAttribute('aria-expanded')!=='true')}})}});
document.querySelectorAll('button.sgc').forEach(function(b){{b.addEventListener('click',function(){{var r=document.getElementById('sd'+b.dataset.sd);if(!r)return;var o=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',o);r.hidden=!o}})}});
document.getElementById('all').onclick=function(){{bs.forEach(function(b){{set(b,true)}})}};document.getElementById('none').onclick=function(){{bs.forEach(function(b){{set(b,false)}})}};}})();
</script><script>
(function(){{var r=document.documentElement,b=document.getElementById('tg');
function cur(){{var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
function lab(){{b.textContent=cur()==='dark'?'Light mode':'Dark mode'}}
try{{var s=localStorage.getItem('ntr-theme');if(s)r.setAttribute('data-theme',s)}}catch(e){{}}
lab();b.addEventListener('click',function(){{var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{{localStorage.setItem('ntr-theme',n)}}catch(e){{}}lab()}});}})();
</script></body></html>'''
open(sys.argv[2],"w").write(page)
if os.environ.get("SUMMARY_DIR"):
    _cm=rows[-1][1]
    json.dump(dict(updated=NOW.strftime("%-d %b %Y, %-I:%M %p"),month=rows[-1][0].rstrip("*"),np=_cm["np"],roas=_cm["roas"],rev=_cm["r"],spend=_cm["s"],
                   total_np=T["np"],since=dt.date.fromisoformat(months[0]+"-01").strftime("%b %Y"),
                   sig=RS["code"],sig_label=PANEL_LABEL,reason=RS["reason"]),open(os.path.join(os.environ["SUMMARY_DIR"],"monthly.json"),"w"))
for n,d in rows: print(n,d["sig"]["label"],"|",d["sig"]["reason"][:90])
