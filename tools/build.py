"""Nightly non-tracked campaign report builder.
Usage: python3 build.py DATA_DIR OUT_HTML [EMAIL_HTML] [REPORT_URL]
DATA_DIR holds raw tool-result files:
  windsor*  : Windsor.ai get_data result (daily rows, any wrapper)
  shopify*  : Shopify graphql_query results (aliases of orders connections)
"""
import json, html, datetime as dt, sys, glob, os
from zoneinfo import ZoneInfo
S=sys.argv[1]; OUT=sys.argv[2]; EMAIL=sys.argv[3] if len(sys.argv)>3 else None; URL=sys.argv[4] if len(sys.argv)>4 else ""
TZ=ZoneInfo("Australia/Sydney"); NOW=dt.datetime.now(TZ)
if os.environ.get("REPORT_NOW"): NOW=dt.datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)
TODAY=NOW.date(); D=dt.timedelta
YEST=TODAY-D(1); WS=TODAY-D(TODAY.weekday()); MS=TODAY.replace(day=1)
PMS=(MS-D(1)).replace(day=1); PME=min(PMS.replace(day=min(TODAY.day,(MS-D(1)).day)),MS-D(1))
M="actions_onsite_conversion_messaging_conversation_started_7d"
def unwrap(x):
    if isinstance(x,dict) and "result" in x: x=x["result"]
    if isinstance(x,dict) and "data" in x and isinstance(x["data"],list): x=x["data"]
    if isinstance(x,list) and x and isinstance(x[0],dict) and "text" in x[0] and "campaign" not in x[0]:
        out=[]
        for p in x: out+=unwrap(json.loads(p["text"]))
        return out
    if isinstance(x,str): return unwrap(json.loads(x))
    return x
rowsw={}
for f in sorted(glob.glob(f"{S}/windsor*")):
    for r in unwrap(json.load(open(f))): rowsw[(r["date"],r["campaign"])]=r
by={}; meta={}
for r in sorted(rowsw.values(),key=lambda r:r["date"]):
    if not r.get("spend") and not r.get(M): continue
    by.setdefault(r["campaign"],{})[r["date"]]=(r["spend"] or 0,r[M] or 0)
    meta[r["campaign"]]=(r.get("campaign_status") or "",(r.get("campaign_start_time") or r["date"])[:10])
ordmap={}
for f in sorted(glob.glob(f"{S}/shopify*")):
    x=json.load(open(f))
    if isinstance(x,dict) and "result" in x: x=x["result"]
    if isinstance(x,list) and x and "text" in x[0]: x=json.loads(x[0]["text"])
    for v in x["data"].values():
        for n in v["nodes"]: ordmap[n["name"]]=n
def cpm(s,m): return None if not s else (s/m if m else float("inf"))
def band(c): return "none" if c is None else "g" if c<4.5 else "y" if c<=6 else "r"
def fcpm(c): return "—" if c is None else ("No msgs" if c==float("inf") else f"${c:.2f}")
def money(v): return "—" if not v else (f"${v:,.0f}" if v>=1000 else f"${v:,.2f}")
def arrow(now,prev,higher_good):
    if now is None or prev is None or now==prev: return ""
    up=now>prev; cls="nt" if higher_good is None else ("gd" if up==higher_good else "bd")
    return f'<i class="ar {cls}" title="{"Up" if up else "Down"} vs previous period">{"▲" if up else "▼"}</i>'
def rng(days,a,b):
    v=[x for d,x in days.items() if str(a)<=d<=str(b)]
    return (sum(x[0] for x in v),sum(x[1] for x in v))
P={"t":(TODAY,TODAY,YEST,YEST),"w":(WS,TODAY,WS-D(7),TODAY-D(7)),"m":(MS,TODAY,PMS,PME)}
rows=[]
for n,days in by.items():
    st,L=meta[n]; L=dt.date.fromisoformat(L)
    r=dict(n=n.replace("Non Tracked | ","").replace(" | Campaign",""),act=st=="ACTIVE",L=L,live=(TODAY-L).days+1)
    for k,(a,b,pa,pb) in P.items(): r[k]=rng(days,a,b); r["p"+k]=rng(days,pa,pb)
    r["l"]=rng(days,"0000","9999")
    spent=sorted(d for d in days if days[d][0]>0)
    r["below"]=sum(1 for d in spent if cpm(*days[d])<4.5); r["ad"]=len(spent)
    run=0
    for d in reversed(spent):
        if d==str(TODAY): continue
        if cpm(*days[d])<4.5: run+=1
        else: break
    r["run"]=run; rows.append(r)
FIRST=min(d for days in by.values() for d in days if days[d][0]>0)
rows.sort(key=lambda r:(not r["act"],-r["m"][0],-r["l"][0]))
tot={k:(sum(r[k][0] for r in rows),sum(r[k][1] for r in rows)) for k in ["t","pt","w","pw","m","pm","l"]}

from zoneinfo import ZoneInfo
FBP="FB/IG PAGE MSGS MEL - SALE"; FBW="FB WHATSAPP MSGS MEL - SALE"
ords=list(ordmap.values())
def odt(n): return dt.datetime.fromisoformat(n["processedAt"].replace("Z","+00:00")).astimezone(TZ)
sales={}  # date -> [pageN,page$,waN,wa$]
tagged_first=None; unatt=[]
for n in ords:
    if n["cancelledAt"]: continue
    t=odt(n); v=(n["m"] or {}).get("value"); a=float(n["t"]["shopMoney"]["amount"])
    if v and (tagged_first is None or t.date()<tagged_first): tagged_first=t.date()
    if v in (FBP,FBW):
        r=sales.setdefault(str(t.date()),[0,0.0,0,0.0]); i=0 if v==FBP else 2; r[i]+=1; r[i+1]+=a
    elif not v: unatt.append((t,n["name"],a,n["sourceName"]))
def srng(a,b):
    v=[x for d,x in sales.items() if str(a)<=d<=str(b)]
    return [sum(x[i] for x in v) for i in range(4)]
def sprng(a,b):
    v=[x for d,x in by.items() for dd,y in x.items() if str(a)<=dd<=str(b) for x in [y]]
    return sum(y[0] for y in v)
SP={k:(srng(a,b),srng(pa,pb)) for k,(a,b,pa,pb) in P.items()}
SP["l"]=(srng("0000","9999"),None)
TF=tagged_first
spend_since_tf=sum(y[0] for x in by.values() for d,y in x.items() if d>=str(TF))
sales_l=SP["l"][0][1]+SP["l"][0][3]
roas_tf=sales_l/spend_since_tf if spend_since_tf else None
unatt=[u for u in unatt if u[0]>=dt.datetime.combine(TF,dt.time(0),tzinfo=TZ)]
u48=[u for u in unatt if NOW-u[0]<=dt.timedelta(hours=48)]
u7=[u for u in unatt if dt.timedelta(hours=48)<NOW-u[0]<=dt.timedelta(days=7)]
uold=[u for u in unatt if NOW-u[0]>dt.timedelta(days=7) and u[2]>0]
# ---- budget signal: profit-maximisation engine (shared with the monthly profitability report) ----
spd={};msd={}
for _c,_days in by.items():
    for _d,(_s,_m) in _days.items(): spd[_d]=spd.get(_d,0)+_s; msd[_d]=msd.get(_d,0)+_m
rvd={d:x[1]+x[3] for d,x in sales.items()}; odd={d:x[0]+x[2] for d,x in sales.items()}
TRACK_START=TF.replace(day=1)
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

G1=TODAY-D(1); G0=G1-D(13)
RS=rolling_signal(G1); c14=RS["cur"]
g_sp,g_ms,g_rev,g_ord=c14["s"],c14["m"],c14["r"],c14["o"]
g_conv=c14["conv"] or 0; g_aov=c14["aov"] or 0; g_cpm=c14["cpm"]; g_be=c14["be"] or 0
SIGCLS={"up":"scale","hold":"hold","down":"cut"}[RS["code"]]
SIG=(SIGCLS,{"up":"Scale Up","hold":"Hold Budget","down":"Scale Down"}[RS["code"]],RS["reason"])
if RS["cmp"] and RS["cmp"]["mode"]=="up": MRV=f'{RS["cmp"]["ratio"]:.2f}'; MRL="marginal return (each extra $1)"
elif RS["cmp"] and RS["cmp"]["mode"]=="down": MRV="Spend fell"; MRL="marginal return: see why"
else: MRV=f'${_headroom(c14):.2f}' if c14 and c14["s"] else "—"; MRL="return per $1 of ads now (spend too steady for the extra-spend test)"
def roasf(x): return "—" if x is None else f"{x:.2f}x"

def trio(cur,prev,lab):
    k={"Today":"t","Week":"w","Month":"m","Lifetime":"l"}[lab]
    s,m=cur; ps,pm=prev if prev and prev[0] else (None,None)
    if not s: return f'<td class="s1 c{k}" data-l="{lab} spend">—</td><td class="c{k}" data-l="{lab} msgs">—</td><td class="c{k}" data-l="{lab} cost/msg">—</td>'
    c=cpm(s,m)
    return (f'<td class="s1 c{k}" data-l="{lab} spend">{money(s)}{arrow(s,ps,None) if ps else ""}</td>'
            f'<td class="c{k}" data-l="{lab} msgs">{int(m):,}{arrow(m,pm,True) if pm is not None else ""}</td>'
            f'<td class="c{k}" data-l="{lab} cost/msg"><span class="p {band(c)}">{fcpm(c)}</span>{arrow(c,cpm(ps,pm),False) if ps else ""}</td>')
trs=""; first_p=True
for r in rows:
    cls="act" if r["act"] else "paused"
    if not r["act"] and first_p: cls+=" firstp"; first_p=False
    pct=round(100*r["below"]/r["ad"]) if r["ad"] else 0
    trs+=(f'<tr class="{cls}"><th scope="row"><span class="nm">{html.escape(r["n"])}</span>'
          f'<span class="meta"><span class="st {"on" if r["act"] else "off"}">{"Active" if r["act"] else "Paused"}</span>Launched {r["L"].strftime("%-d %b %Y")} ({r["live"]} days)</span></th>'
          + trio(r["t"],r["pt"],"Today")+trio(r["w"],r["pw"],"Week")+trio(r["m"],r["pm"],"Month")+trio(r["l"],None,"Lifetime")
          + f'<td class="s1 streak" data-l="Days under $4.50"><b>{r["below"]}</b> of {r["ad"]} days<span class="bar"><span style="width:{pct}%"></span></span>'
          f'<small>{("Current run: "+str(r["run"])+(" day" if r["run"]==1 else " days")) if r["act"] else "Paused"}</small></td></tr>')
trs+=('<tr class="total"><th scope="row">All non-tracked campaigns</th>'+trio(tot["t"],tot["pt"],"Today")+trio(tot["w"],tot["pw"],"Week")
      +trio(tot["m"],tot["pm"],"Month")+trio(tot["l"],None,"Lifetime")+'<td class="s1"></td></tr>')

def kpi(k,label,rng,cur,prev,note,sp=None,extra=""):
    s,m=cur; c=cpm(s,m); ps,pm=prev if prev else (None,None)
    cs,psl=sp if sp else ([0,0,0,0],None)
    sv=cs[1]+cs[3]; so=cs[0]+cs[2]; r=sv/s if s else None
    if psl: pv=psl[1]+psl[3]; po=psl[0]+psl[2]; pr=pv/ps if ps else None
    else: pv=po=pr=None
    srow=(f'<div class="kv sv"><div><b>{money(sv) if sv else "$0"}{arrow(sv,pv,True) if pv is not None else ""}</b><span>FB sales</span></div>'
          f'<div><b>{so}{arrow(so,po,True) if po is not None else ""}</b><span>orders</span></div>'
          f'<div><b class="ro">{roasf(r)}{arrow(r,pr,True) if (pr is not None and r is not None) else ""}</b><span>ROAS</span></div></div>{extra}')
    return (f'<div class="kpi k{k}"><h2>{label}</h2><p class="rg">{rng}</p><div class="kv">'
            f'<div><b>{money(s)}{arrow(s,ps,None) if ps else ""}</b><span>spent</span></div>'
            f'<div><b>{int(m):,}{arrow(m,pm,True) if pm is not None else ""}</b><span>messages</span></div>'
            f'<div><b><span class="p {band(c)}">{fcpm(c)}</span>{arrow(c,cpm(ps,pm),False) if ps else ""}</b><span>per message</span></div>'
            f'</div>'+srow+f'<p class="kn">{note}</p></div>')
DK="--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--gl:#27604A;--y:#F2C85B;--yb:#362A0E;--yl:#6B5419;--r:#FF8C80;--rb:#3D1A17;--rl:#7A3129;--t:#8FB2FF;--tb:#1A2B52;--tc:#141E36;--w:#C3A6FF;--wb:#2C2150;--wc:#1D1834;--m:#5FD4C6;--mb:#123D3A;--mc:#0F2927;--l:#FFB085;--lb:#43261A;--lc:#2C1B14"
def cells(i):
    out=""
    for k in "twml":
        cs=SP[k][0]; ps=SP[k][1]
        v=cs[i]; pv=ps[i] if ps else None
        fmt=(money(v) if v else "$0") if i%2 else str(v)
        out+=f'<td class="c{k}" data-l="{ {"t":"Today","w":"This week","m":"This month","l":"Lifetime"}[k] }">{fmt}{arrow(v,pv,True) if pv is not None else ""}</td>'
    return out
def ulist(L):
    if not L: return '<p class="ok">All orders have an order source.</p>'
    items="".join(f'<li><b>{html.escape(n)}</b> {t.strftime("%a %-d %b, %-I:%M %p")} <span>{money(a) if a else "$0"}</span></li>' for t,n,a,_ in sorted(L))
    return f'<p class="bad"><b>{len(L)} {"order" if len(L)==1 else "orders"}, {money(sum(a for *_,a,_ in [(x[0],x[1],x[2],x[3]) for x in L]))}</b> without an order source</p><ul>{items}</ul>'
SIGP=f'''<section class="sig {SIG[0]}"><div class="sg"><span class="sgl">Budget signal</span><b>{SIG[1]}</b><p>{SIG[2]}</p></div>
<div class="sgm"><div><b>{money(g_cpm) if g_cpm else "—"}</b><span>cost per message</span></div><div><b>{money(g_be)}</b><span>break-even per message</span></div><div><b>{g_conv*100:.1f}%</b><span>messages to orders</span></div><div><b>{money(g_aov) if g_aov else "—"}</b><span>average order</span></div><div><b>{MRV}</b><span>{MRL}</span></div></div>
<p class="sgn">Last 14 full days, {G0.strftime("%-d %b")} to {G1.strftime("%-d %b")}: {money(g_sp)} spend, {int(g_ms):,} messages, {g_ord} FB orders, {money(g_rev)} revenue, {money(c14["p"])} net profit. Break-even = revenue per message × 0.68 (what's left after GST and product cost); a safety guardrail, not the decision.</p>
<details class="sgn why"><summary>Why this signal</summary><ul>{"".join(f"<li>{html.escape(x)}</li>" for x in RS["details"])}</ul></details></section>'''
SECTION=SIGP+f'''<section class="two">
<div class="box"><h2>FB sales by message channel</h2><p class="sub">Shopify orders tagged with these two order sources. Values include GST, after refunds.</p>
<div class="tw"><table class="mini"><thead><tr><th></th><th class="ct">Today</th><th class="cw">This week</th><th class="cm">This month</th><th class="cl">Lifetime</th></tr></thead><tbody>
<tr><th scope="row">FB/IG page messages, orders</th>{cells(0)}</tr>
<tr><th scope="row">FB/IG page messages, sales</th>{cells(1)}</tr>
<tr><th scope="row">WhatsApp messages, orders</th>{cells(2)}</tr>
<tr><th scope="row">WhatsApp messages, sales</th>{cells(3)}</tr>
</tbody></table></div></div>
<div class="box att"><h2>Orders to attribute</h2><p class="sub">Orders with an empty order source. Fill these in so the next report picks them up.</p>
<h3>Last 48 hours</h3>{ulist(u48)}
<h3>3 to 7 days ago</h3>{ulist(u7)}
<p class="old">Older backlog since {TF.strftime("%-d %b %Y")}: {len(uold)} paid orders, {money(sum(u[2] for u in uold))} still without a source.</p></div>
</section>'''
page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Non-tracked campaigns daily report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Figtree:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{
--bg:#F6F7F9;--card:#FFFFFF;--ink:#101828;--muted:#5A6272;--line:#D9DEE6;--sub:#EEF1F5;--mari:#E8A317;
--g:#17694A;--gb:#D5F2E3;--gl:#9ED9BC;--y:#7A4E00;--yb:#FFEDBF;--yl:#F0CF7A;--r:#A8231B;--rb:#FFE0DC;--rl:#F2A89F;
--t:#1D4ED8;--tb:#DCE7FF;--tc:#EEF3FF;
--w:#6D28D9;--wb:#ECE3FF;--wc:#F5F0FF;
--m:#0F766E;--mb:#D3F2EE;--mc:#EAF8F6;
--l:#9A3412;--lb:#FCE6D6;--lc:#FEF3EA}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{DK}}}}}
:root[data-theme="dark"]{{{DK}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.45 Figtree,system-ui,-apple-system,"Segoe UI",sans-serif;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
main{{max-width:1560px;margin:0 auto;padding:24px 16px 48px}}
header{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:20px}}
.hd{{border-left:6px solid var(--mari);padding-left:14px}}
h1{{font:700 clamp(24px,4vw,36px)/1.1 "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 4px}}
.hd p{{margin:0;color:var(--muted)}}
.tg{{flex:none;font:600 13px Figtree,sans-serif;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:99px;padding:7px 14px;cursor:pointer}}
.tg:focus-visible{{outline:3px solid var(--t);outline-offset:2px}}
.kt{{--pc:var(--t);--pb:var(--tb);--pcol:var(--tc)}}.kw{{--pc:var(--w);--pb:var(--wb);--pcol:var(--wc)}}
.km{{--pc:var(--m);--pb:var(--mb);--pcol:var(--mc)}}.kl{{--pc:var(--l);--pb:var(--lb);--pcol:var(--lc)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin-bottom:14px}}
.kpi{{background:var(--pb);border-radius:12px;padding:14px 16px;border:1px solid color-mix(in srgb,var(--pc) 30%,transparent)}}
.kpi h2{{font:700 16px/1.2 "Bricolage Grotesque",Figtree,sans-serif;margin:0;color:var(--pc)}}
.rg{{margin:2px 0 12px;font-weight:600;font-size:12px;color:var(--ink)}}
.rg span{{font-weight:400;color:var(--muted)}}
.kv{{display:grid;grid-template-columns:repeat(3,auto);justify-content:space-between;gap:8px}}
.kv b{{display:block;font:700 21px/1.2 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums;white-space:nowrap}}
.kv b .p{{font:inherit;padding:0 6px}}.kv span{{color:var(--muted);font-size:13px}}
.kn{{margin:10px 0 0;font-size:12.5px;color:var(--muted)}}
.key{{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:13px;color:var(--muted);margin:0 0 14px;align-items:center}}
.wrap{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
thead th{{font-weight:600;font-size:13px;color:var(--muted);padding:8px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}}
thead tr:first-child th{{text-align:left;border-bottom:0;padding-top:12px}}
thead th:first-child{{text-align:left}}
.s1{{border-left:2px solid var(--card)}}
td.ct,th.ct{{--pc:var(--t);--pb:var(--tb);--pcol:var(--tc)}}td.cw,th.cw{{--pc:var(--w);--pb:var(--wb);--pcol:var(--wc)}}
td.cm,th.cm{{--pc:var(--m);--pb:var(--mb);--pcol:var(--mc)}}td.cl,th.cl{{--pc:var(--l);--pb:var(--lb);--pcol:var(--lc)}}
td.ct,td.cw,td.cm,td.cl{{background:var(--pcol)}}
thead th.ct,thead th.cw,thead th.cm,thead th.cl{{background:var(--pb);color:var(--pc)}}
thead th.gh{{font:700 15px/1.2 "Bricolage Grotesque",Figtree,sans-serif}}
thead th.gh small{{display:block;font:500 12px Figtree,sans-serif;color:var(--ink);opacity:.75}}
tbody th{{text-align:left;font-weight:500;padding:12px;min-width:190px;max-width:230px;position:sticky;left:0;background:var(--card);z-index:1}}
.nm{{display:block}}.meta{{display:block;font-size:12.5px;color:var(--muted);font-weight:400;margin-top:2px}}
.st{{display:inline-block;font-size:12px;font-weight:600;padding:0 7px;border-radius:99px;margin-right:6px}}
.st.on{{background:var(--gb);color:var(--g)}}.st.off{{background:var(--sub);color:var(--muted)}}
td{{padding:12px 8px;text-align:right;white-space:nowrap}}
tbody tr+tr{{border-top:1px solid var(--line)}}
tr.paused td,tr.paused .nm{{color:var(--muted)}}
tr.firstp{{border-top:3px solid var(--line)!important}}
tr.total th{{background:var(--sub);font-weight:700}}
tr.total td.ct,tr.total td.cw,tr.total td.cm,tr.total td.cl{{background:var(--pb);font-weight:700}}
.p{{display:inline-block;padding:1px 7px;border-radius:6px;font-weight:600;border:1px solid transparent}}
.p.g{{background:var(--gb);color:var(--g);border-color:var(--gl)}}.p.y{{background:var(--yb);color:var(--y);border-color:var(--yl)}}.p.r{{background:var(--rb);color:var(--r);border-color:var(--rl)}}.p.none{{font-weight:400}}
.ar{{font-style:normal;font-size:11px;margin-left:4px;vertical-align:1px}}.ar.gd{{color:var(--g)}}.ar.bd{{color:var(--r)}}.ar.nt{{color:var(--muted)}}
.streak{{text-align:left;min-width:140px}}.streak b{{font-size:16px}}.streak small{{display:block;color:var(--muted)}}
.bar{{display:block;height:5px;background:var(--rb);border-radius:3px;margin:5px 0 3px;overflow:hidden}}.bar span{{display:block;height:100%;background:var(--g)}}
.sig{{display:grid;grid-template-columns:minmax(220px,1fr) 3fr;gap:10px 20px;align-items:center;background:var(--card);border:1px solid var(--line);border-left:6px solid var(--sc);border-radius:12px;padding:14px 16px;margin-bottom:14px}}
.sig.scale{{--sc:var(--g)}}.sig.hold{{--sc:var(--y)}}.sig.cut{{--sc:var(--r)}}
.sgl{{display:block;font-size:12.5px;color:var(--muted);font-weight:600}}
.sg b{{display:block;font:700 22px/1.2 "Bricolage Grotesque",Figtree,sans-serif;color:var(--sc)}}
.sg p{{margin:4px 0 0;font-size:13px;color:var(--muted)}}
.sgm{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
.sgm b{{display:block;font:700 19px/1.2 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums}}.sgm span{{font-size:12.5px;color:var(--muted)}}
.sgn{{grid-column:1/-1;margin:0;font-size:12.5px;color:var(--muted)}}
.why summary{{cursor:pointer;font-weight:600;color:var(--ink)}}.why ul{{margin:6px 0 0;padding-left:18px}}.why li{{margin:2px 0}}
@media (max-width:700px){{.sig{{grid-template-columns:1fr}}}}
.kv.sv{{margin-top:10px;padding-top:10px;border-top:1px solid color-mix(in srgb,var(--pc) 30%,transparent)}}
.kn2{{margin:8px 0 0;font-size:12.5px;color:var(--ink)}}
.two{{display:grid;grid-template-columns:3fr 2fr;gap:12px;margin-bottom:16px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;min-width:0}}
.box h2{{font:700 17px/1.2 "Bricolage Grotesque",Figtree,sans-serif;margin:0 0 2px}}
.box h3{{font:600 14px/1.2 Figtree,sans-serif;margin:12px 0 4px}}
.sub{{margin:0 0 10px;color:var(--muted);font-size:13px}}
.tw{{overflow-x:auto}}
table.mini td,table.mini th{{padding:9px 10px}}
table.mini tbody th{{position:static;min-width:170px;font-weight:500}}
table.mini thead th{{text-align:right;font:700 14px "Bricolage Grotesque",Figtree,sans-serif}}
table.mini tbody tr:nth-child(2) td,table.mini tbody tr:nth-child(4) td{{font-weight:700}}
.att .ok{{margin:0;color:var(--g);font-weight:600}}
.att .bad{{margin:0 0 4px;color:var(--r)}}
.att ul{{margin:0;padding-left:18px;font-size:13.5px}}.att li span{{color:var(--r);font-weight:600;margin-left:4px}}
.att .old{{margin:12px 0 0;font-size:12.5px;color:var(--muted)}}
@media (max-width:900px){{.two{{grid-template-columns:1fr}} table.mini thead{{display:table-header-group}} table.mini,table.mini tbody{{display:table;width:100%}} table.mini tr{{display:table-row!important;border:0!important;border-radius:0;margin:0}} table.mini th,table.mini td{{display:table-cell;width:auto}} table.mini td::before{{display:none}} table.mini tbody th{{min-width:120px;font-size:13px}}}}
.foot{{color:var(--muted);font-size:13px;margin:12px 2px 0;max-width:80ch}}
@media (max-width:900px){{
 thead{{display:none}}table,tbody,tr,th,td{{display:block;width:100%}}
 .wrap{{background:none;border:0;overflow:visible}}
 tbody tr{{background:var(--card);border:1px solid var(--line)!important;border-radius:12px;margin-bottom:10px;display:grid;grid-template-columns:repeat(3,1fr);overflow:hidden}}
 tbody th{{grid-column:1/-1;position:static;min-width:0;max-width:none;border-bottom:1px solid var(--line)}}
 td{{text-align:left;padding:8px 12px;border:0!important;white-space:normal}}
 td::before{{content:attr(data-l);display:block;font-size:12px;color:var(--pc,var(--muted));font-weight:700}}
 td.streak{{grid-column:1/-1}}
 tr.total td:last-child{{display:none}}
 header{{flex-direction:column}}
}}
</style></head><body><main>
<header><div class="hd"><h1>Non-tracked campaigns, daily</h1><p>Webirox ad account, Meta messaging campaigns. Report for {TODAY.strftime("%A %-d %B %Y")}, updated {NOW.strftime("%-I:%M %p")} Sydney time.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
<section class="kpis">
{kpi("t","Today",TODAY.strftime("%a %-d %b %Y"),tot["t"],tot["pt"],"Arrows compare with yesterday, "+YEST.strftime("%a %-d %b")+".",SP["t"])}
{kpi("w","This week",WS.strftime("%-d %b")+" to "+(WS+D(6)).strftime("%-d %b %Y")+' <span>(data to '+TODAY.strftime("%-d %b")+')</span>',tot["w"],tot["pw"],"Arrows compare with "+((WS-D(7)).strftime("%a %-d")+" to " if WS!=TODAY else "")+(TODAY-D(7)).strftime("%a %-d %b")+".",SP["w"])}
{kpi("m","This month",MS.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b %Y"),tot["m"],tot["pm"],"Arrows compare with "+PMS.strftime("%-d")+" to "+PME.strftime("%-d %b")+".",SP["m"])}
{kpi("l","Lifetime",dt.date.fromisoformat(FIRST).strftime("%-d %b %Y")+" to "+TODAY.strftime("%-d %b %Y"),tot["l"],None,f"All {len(rows)} non-tracked campaigns, active and paused, from the first day of spend. Sales are only recorded from {TF.strftime('%-d %b %Y')}, when order sources started being filled in, so lifetime ROAS is understated.",SP["l"],f'<p class="kn2">ROAS since {TF.strftime("%-d %b %Y")}: <b>{roasf(roas_tf)}</b> ({money(sales_l)} sales on {money(spend_since_tf)} spend)</p>')}
</section>
{SECTION}
<p class="key"><span class="p g">Under $4.50</span><span class="p y">$4.50 to $6</span><span class="p r">Over $6</span><span>▲▼ change vs the previous period: green is better, red is worse, grey is spend</span></p>
<div class="wrap"><table>
<thead><tr><th></th><th colspan="3" class="s1 gh ct">Today<small>{TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cw">This week<small>{WS.strftime("%-d %b")} to {(WS+D(6)).strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cm">This month<small>{MS.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cl">Lifetime<small>Since {dt.date.fromisoformat(FIRST).strftime("%-d %b %Y")}</small></th><th class="s1">Days under $4.50</th></tr>
<tr><th>Campaign</th>{"".join(f'<th class="s1 c{k}">Spend</th><th class="c{k}">Msgs</th><th class="c{k}">Cost/msg</th>' for k in "twml")}<th class="s1">Since launch</th></tr></thead>
<tbody>{trs}</tbody></table></div>
<p class="foot">Messages are Meta "messaging conversations started". Days under $4.50 counts days with spend where cost per message stayed under $4.50; a day with spend but no messages counts as over. Current run is the unbroken count of such days up to yesterday.</p>
</main>
<script>
(function(){{var r=document.documentElement,b=document.getElementById('tg');
function cur(){{var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
function lab(){{b.textContent=cur()==='dark'?'Light mode':'Dark mode'}}
try{{var s=localStorage.getItem('ntr-theme');if(s)r.setAttribute('data-theme',s)}}catch(e){{}}
lab();b.addEventListener('click',function(){{var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{{localStorage.setItem('ntr-theme',n)}}catch(e){{}}lab()}});}})();
</script></body></html>'''
open(OUT,"w").write(page)
for k,v in tot.items(): print(k,round(v[0],2),v[1])

# ---------- email version (inline styles, works in Gmail/Outlook) ----------
PC={"t":("#1D4ED8","#DCE7FF","#EEF3FF"),"w":("#6D28D9","#ECE3FF","#F5F0FF"),"m":("#0F766E","#D3F2EE","#EAF8F6"),"l":("#9A3412","#FCE6D6","#FEF3EA")}
BAND={"g":("#17694A","#D5F2E3"),"y":("#7A4E00","#FFEDBF"),"r":("#A8231B","#FFE0DC"),"none":("#5A6272","transparent")}
def epill(c):
    fg,bg=BAND[band(c)]; return f'<span style="background:{bg};color:{fg};font-weight:700;padding:1px 6px;border-radius:5px">{fcpm(c)}</span>'
def earr(now,prev,hg):
    if now is None or prev is None or now==prev: return ""
    up=now>prev; col="#5A6272" if hg is None else ("#17694A" if up==hg else "#A8231B")
    return f' <span style="color:{col};font-size:11px">{"&#9650;" if up else "&#9660;"}</span>'
def per(k):
    s,m=tot[k]; ps,pm=tot.get("p"+k,(None,None)) if k!="l" else (None,None)
    cs,psl=SP[k]; sv=cs[1]+cs[3]; so=cs[0]+cs[2]; r=sv/s if s else None
    pv=po=pr=None
    if psl: pv=psl[1]+psl[3]; po=psl[0]+psl[2]; pr=pv/ps if ps else None
    return dict(s=s,m=m,ps=ps,pm=pm,sv=sv,so=so,r=r,pv=pv,po=po,pr=pr)
PR={k:per(k) for k in "twml"}
LAB={"t":("Today",TODAY.strftime("%-d %b")),"w":("This week",WS.strftime("%-d %b")+" to "+(WS+D(6)).strftime("%-d %b")),"m":("This month",MS.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b")),"l":("Lifetime","Since "+dt.date.fromisoformat(FIRST).strftime("%-d %b %Y"))}
def ecell(k,inner,bold=False):
    return f'<td style="background:{PC[k][2]};padding:8px 10px;text-align:right;white-space:nowrap;{"font-weight:700;" if bold else ""}">{inner}</td>'
TH="padding:8px 10px;text-align:left;font-weight:600;color:#101828;white-space:nowrap"
hdr="".join(f'<th style="background:{PC[k][1]};color:{PC[k][0]};padding:8px 10px;text-align:right;white-space:nowrap">{LAB[k][0]}<br><span style="font-weight:400;font-size:11px;color:#5A6272">{LAB[k][1]}</span></th>' for k in "twml")
def row(label,fn,bold=False): return f'<tr style="border-top:1px solid #D9DEE6"><th style="{TH}">{label}</th>'+"".join(ecell(k,fn(PR[k]),bold) for k in "twml")+'</tr>'
summary=('<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;font-size:14px">'
 f'<tr><th></th>{hdr}</tr>'
 +row("Spend",lambda p:money(p["s"])+earr(p["s"],p["ps"],None))
 +row("Messages",lambda p:f'{int(p["m"]):,}'+earr(p["m"],p["pm"],True))
 +row("Cost per message",lambda p:epill(cpm(p["s"],p["m"]))+earr(cpm(p["s"],p["m"]),cpm(p["ps"],p["pm"]) if p["ps"] else None,False))
 +row("FB sales",lambda p:(money(p["sv"]) if p["sv"] else "$0")+earr(p["sv"],p["pv"],True),True)
 +row("FB orders",lambda p:str(p["so"])+earr(p["so"],p["po"],True))
 +row("ROAS",lambda p:roasf(p["r"])+(earr(p["r"],p["pr"],True) if p["r"] is not None and p["pr"] is not None else ""),True)
 +'</table>')
act=[r for r in rows if r["act"]]
crow=""
for r in act:
    crow+=('<tr style="border-top:1px solid #D9DEE6">'
      f'<td style="padding:8px 10px">{html.escape(r["n"])}<br><span style="font-size:11px;color:#5A6272">Launched {r["L"].strftime("%-d %b %Y")}</span></td>'
      f'<td style="background:{PC["t"][2]};padding:8px 10px;text-align:right;white-space:nowrap">{money(r["t"][0]) if r["t"][0] else "—"}<br>{int(r["t"][1])} msgs {epill(cpm(*r["t"])) if r["t"][0] else ""}</td>'
      f'<td style="background:{PC["m"][2]};padding:8px 10px;text-align:right;white-space:nowrap">{money(r["m"][0])}<br>{epill(cpm(*r["m"]))}</td>'
      f'<td style="background:{PC["l"][2]};padding:8px 10px;text-align:right;white-space:nowrap">{epill(cpm(*r["l"]))}</td>'
      f'<td style="padding:8px 10px;white-space:nowrap"><b>{r["below"]}</b> of {r["ad"]} days<br><span style="font-size:11px;color:#5A6272">Run: {r["run"]}</span></td></tr>')
def elist(L,title):
    if not L: return f'<p style="margin:4px 0;color:#17694A"><b>{title}:</b> all orders have an order source.</p>'
    return (f'<p style="margin:4px 0;color:#A8231B"><b>{title}: {len(L)} orders, {money(sum(u[2] for u in L))} without an order source</b></p><ul style="margin:0 0 6px;padding-left:18px">'
            +"".join(f'<li>{html.escape(n)}, {t.strftime("%a %-d %b %-I:%M %p")}, {money(a) if a else "$0"}</li>' for t,n,a,_ in sorted(L))+'</ul>')
btn=f'<p style="margin:18px 0"><a href="{html.escape(URL)}" style="background:#1D4ED8;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700">Open the full report</a></p>' if URL else ""
email=f'''<div style="font-family:Arial,Helvetica,sans-serif;color:#101828;max-width:760px">
<h2 style="margin:0 0 4px">Non-tracked campaigns, {TODAY.strftime("%a %-d %b %Y")}</h2>
<p style="margin:0 0 14px;color:#5A6272">Meta messaging campaigns and FB-attributed Shopify sales. Updated {NOW.strftime("%-I:%M %p")} Sydney time.</p>
{summary}
<p style="font-size:12px;color:#5A6272;margin:6px 0 16px">Arrows compare with the previous period. Cost per message: green under $4.50, yellow $4.50 to $6, red over $6. FB sales are orders tagged FB/IG page messages or WhatsApp messages, including GST. Sales are only recorded from {TF.strftime("%-d %b %Y")}; ROAS since then is {roasf(roas_tf)}.</p>
<div style="border-left:5px solid {({"scale":"#17694A","hold":"#B7791F","cut":"#A8231B"})[SIG[0]]};background:#F6F7F9;padding:10px 14px;margin:6px 0 14px">
<b style="font-size:16px;color:{({"scale":"#17694A","hold":"#7A4E00","cut":"#A8231B"})[SIG[0]]}">Budget signal: {SIG[1]}</b><br>
<span style="font-size:13px">{html.escape(SIG[2])} Last 14 days: cost per message {money(g_cpm) if g_cpm else "—"}, break-even {money(g_be)}, messages to orders {g_conv*100:.1f}%, average order {money(g_aov) if g_aov else "—"}, marginal return {MRV}.</span></div>
<h3 style="margin:16px 0 6px">Active campaigns</h3>
<table cellspacing="0" cellpadding="0" style="border-collapse:collapse;width:100%;font-size:13px">
<tr><th style="{TH}">Campaign</th><th style="background:{PC["t"][1]};color:{PC["t"][0]};padding:8px 10px;text-align:right">Today</th><th style="background:{PC["m"][1]};color:{PC["m"][0]};padding:8px 10px;text-align:right">This month</th><th style="background:{PC["l"][1]};color:{PC["l"][0]};padding:8px 10px;text-align:right">Lifetime</th><th style="{TH}">Under $4.50</th></tr>
{crow}</table>
<h3 style="margin:18px 0 6px">Orders to attribute</h3>
{elist(u48,"Last 48 hours")}{elist(u7,"3 to 7 days ago")}
<p style="margin:4px 0;font-size:12px;color:#5A6272">Older backlog since {TF.strftime("%-d %b %Y")}: {len(uold)} paid orders, {money(sum(u[2] for u in uold))}.</p>
{btn}</div>'''
if EMAIL: open(EMAIL,"w").write(email)
p=PR["m"]; t=PR["t"]
worst=max((r for r in act if r["t"][0]),key=lambda r:cpm(*r["t"]) if r["t"][1] else 1e9,default=None)
if os.environ.get("SUMMARY_DIR"):
    json.dump(dict(updated=NOW.strftime("%-d %b %Y, %-I:%M %p"),t_s=t["s"],t_m=t["m"],t_cpm=cpm(t["s"],t["m"]) if t["m"] else None,
                   m_s=p["s"],m_sales=p["sv"],m_roas=p["r"],m_cpm=cpm(p["s"],p["m"]),active=len(act),
                   unatt=len(u48)+len(u7),sig=RS["code"],sig_label=SIG[1],reason=SIG[2]),open(os.path.join(os.environ["SUMMARY_DIR"],"daily.json"),"w"))
print("PUSH: "+f"Non-tracked {TODAY.strftime('%-d %b')} | Today ${t['s']:.0f}, {int(t['m'])} msgs, {fcpm(cpm(t['s'],t['m']))}/msg, FB sales {money(t['sv']) if t['sv'] else '$0'} | MTD ROAS {roasf(p['r'])} | {SIG[1]}"+(f" | {len(u48)+len(u7)} orders need a source" if (u48 or u7) else ""))
