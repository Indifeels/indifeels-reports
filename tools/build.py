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
# Final-report cutoff: the latest fully completed Sydney calendar day.
# When REPORT_NOW is supplied as 23:59 on yesterday, TODAY intentionally becomes that completed day.
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
# Periods: latest day, last 7 days, last 30 days (all ending on the report day), then lifetime.
W7=TODAY-D(6); M15=TODAY-D(14); M30=TODAY-D(29)
REAL=dt.datetime.now(TZ).date()
LBL_T="Today" if TODAY>=REAL else ("Yesterday" if TODAY==REAL-D(1) else TODAY.strftime("%A"))
FULL_END=TODAY if TODAY<REAL else TODAY-D(1)   # last fully completed day: used for health, rank and spend signal
P={"t":(TODAY,TODAY,YEST,YEST),"w":(W7,TODAY,W7-D(7),W7-D(1)),"x":(M15,TODAY,M15-D(15),M15-D(1)),"m":(M30,TODAY,M30-D(30),M30-D(1))}
rows=[]
for n,days in by.items():
    st,L=meta[n]; L=dt.date.fromisoformat(L)
    r=dict(key=n,n=n.replace("Non Tracked | ","").replace(" | Campaign",""),act=st=="ACTIVE",L=L,live=(TODAY-L).days+1)
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
tot={k:(sum(r[k][0] for r in rows),sum(r[k][1] for r in rows)) for k in ["t","pt","w","pw","x","px","m","pm","l"]}

# ---- ad sets, health, rank and spend signal (campaign and ad-set level) ----
MIN_SPEND=20.0
H30=(FULL_END-D(29),FULL_END); H15=(FULL_END-D(14),FULL_END); H7=(FULL_END-D(6),FULL_END)
adrows=[]
for _f in sorted(glob.glob(f"{S}/adset*")): adrows+=unwrap(json.load(open(_f)))
asd={}
for _r in sorted(adrows,key=lambda r:r["date"]):
    if not _r.get("spend") and not _r.get(M): continue
    _a=asd.setdefault(_r["campaign"],{}).setdefault(_r["adset_id"],dict(name=_r.get("adset_name") or _r["adset_id"],days={},act=False))
    _a["name"]=_r.get("adset_name") or _a["name"]; _a["act"]=(_r.get("adset_status") or "")=="ACTIVE"
    _a["days"][_r["date"]]=(_r["spend"] or 0,_r[M] or 0)
def metrics(days,act):
    m={}
    for k,(a,b,pa,pb) in P.items(): m[k]=rng(days,a,b); m["p"+k]=rng(days,pa,pb)
    m["l"]=rng(days,"0000","9999")
    m["f30"]=rng(days,*H30); m["f15"]=rng(days,*H15); m["f7"]=rng(days,*H7)
    sp=[d for d in days if days[d][0]>0 and str(H30[0])<=d<=str(H30[1])]
    m["hn"]=len(sp); m["hb"]=sum(1 for d in sp if cpm(*days[d])<4.5); m["act"]=act
    def _hw(h):
        d_=[d for d in days if days[d][0]>0 and str(h[0])<=d<=str(h[1])]
        return (sum(1 for d in d_ if cpm(*days[d])<4.5),len(d_))
    m["h7"]=_hw(H7); m["h15"]=_hw(H15)
    allsp=sorted(d for d in days if days[d][0]>0 and d<=str(FULL_END))
    m["lh"]=(sum(1 for d in allsp if cpm(*days[d])<4.5),len(allsp))
    if allsp:
        m["ls"]=dt.date.fromisoformat(allsp[-1]); _lr=[allsp[-1]]
        for d in reversed(allsp[:-1]):
            if (dt.date.fromisoformat(_lr[-1])-dt.date.fromisoformat(d)).days>3: break
            _lr.append(d)
        m["lr"]=(sum(1 for d in _lr if cpm(*days[d])<4.5),len(_lr))
    else: m["ls"]=None; m["lr"]=(0,0)
    s30,m30=m["f30"]
    if not act: m["health"]=("none","Paused")
    elif m["hn"]<3: m["health"]=("none","New")
    else:
        pct=m["hb"]/m["hn"]
        m["health"]=("r","Poor") if (pct<0.35 or (s30>0 and not m30)) else (("g","Good") if pct>=0.60 else ("y","Watch"))
    return m
def pctl(vals,higher_good):
    ids=list(vals); n=len(ids)
    if n==1: return {ids[0]:1.0}
    out={}
    for i in ids:
        worse=sum(1 for j in ids if j!=i and ((vals[j]<vals[i]) if higher_good else (vals[j]>vals[i])))
        tie=sum(1 for j in ids if j!=i and vals[j]==vals[i])
        out[i]=(worse+0.5*tie)/(n-1)
    return out
def rank_group(ms):
    """Score = 70% messages received + 30% cost per message (each as a percentile among peers).
    Final = 60% last 30 days + 40% last 7 days (full days). Under $20 spend in a window = not ranked on that window."""
    def score(win):
        el={i:v[win] for i,v in ms.items() if v[win][0]>=MIN_SPEND}
        if not el: return {}
        a=pctl({i:v[1] for i,v in el.items()},True); b=pctl({i:cpm(*v) for i,v in el.items()},False)
        return {i:0.7*a[i]+0.3*b[i] for i in el}
    s30=score("f30"); s15=score("f15"); s7=score("f7")
    fin={i:(0.6*s30[i]+0.4*s7[i] if i in s7 else s30[i]) for i in s30}
    order=sorted(fin,key=lambda i:(-fin[i],-ms[i]["f30"][1]))
    o15=sorted(s15,key=lambda i:(-s15[i],-ms[i]["f15"][1])); o7=sorted(s7,key=lambda i:(-s7[i],-ms[i]["f7"][1])); o30=sorted(s30,key=lambda i:(-s30[i],-ms[i]["f30"][1]))
    return {i:dict(rank=order.index(i)+1,n=len(order),r7=(o7.index(i)+1 if i in s7 else None),r15=(o15.index(i)+1 if i in s15 else None),r30=o30.index(i)+1,n7=len(o7),n15=len(o15),n30=len(o30)) for i in order}
def sig_for(m):
    if not m["act"]: return None
    (s30,m30),(s7,m7)=m["f30"],m["f7"]
    if s30<MIN_SPEND and s7<MIN_SPEND: return ("hold","Hold","Too little spend to judge yet")
    c7=cpm(s7,m7) if s7 else None; c30=cpm(s30,m30) if s30 else None
    if m["health"][0]=="r": return ("down","Spend less","Health is poor")
    if c7 is not None and c7>6: return ("down","Spend less","7 days of spend, no messages" if c7==float("inf") else "7-day cost per message is over $6")
    if m["health"][0]=="g" and c7 is not None and c30 is not None and c7<=c30: return ("up","Spend more",f"7-day {fcpm(c7)} is at or below 30-day {fcpm(c30)}")
    return ("hold","Hold","Not clearly better or worse")
def _rag(p,n): return "n" if n<3 else ("g" if p>=0.60 else ("y" if p>=0.35 else "r"))
def finalize(ents):
    """Number the flags inside one group: Close #1 = worst active; Reopen #1 = best paused (70% lifetime messages, 30% lifetime cost per message)."""
    cl=[x for x in ents if x.get("flag") and x["flag"][0]=="close"]
    cl.sort(key=lambda x:(-x["rank"]["rank"],-x["f30"][0]))
    for k,x in enumerate(cl,1): x["flag"]=("close",f"Close #{k}",x["flag"][2]+f". Worst first, {k} of {len(cl)}.")
    for x in cl: x["cr"]=dict(k=int(x["flag"][1].split("#")[1]),n=len(cl))
    ro=[x for x in ents if x.get("flag") and x["flag"][0]=="reopen"]
    if ro:
        ids=list(range(len(ro)))
        a=pctl({i:ro[i]["l"][1] for i in ids},True); b=pctl({i:cpm(*ro[i]["l"]) for i in ids},False)
        sc={i:0.7*a[i]+0.3*b[i] for i in ids}; order=sorted(ids,key=lambda i:-sc[i])
        om=sorted(ids,key=lambda i:-ro[i]["l"][1]); oc=sorted(ids,key=lambda i:cpm(*ro[i]["l"]))
        for k,i in enumerate(order,1):
            x=ro[i]; x["flag"]=("reopen",f"Reopen #{k}",x["flag"][2]+f" Best first, {k} of {len(ro)}.")
            x["rr"]=dict(n=len(ro),k=k,mp=om.index(i)+1,cp=oc.index(i)+1)
def flag_for(m):
    """Active: Consider closing = 30-day health Poor, 7-day health Poor or too thin to read, at least $20 spent in 30 days, and ranked last in its group.
    Paused: Consider reopening = lifetime health Good over at least 5 spend days and $50 spend; Keep closed = lifetime health Poor on the same evidence."""
    if m["act"]:
        b30,n30=m["hb"],m["hn"]; b7,n7=m["h7"]; rk=m.get("rank")
        if n30>=3 and _rag(b30/n30,n30) in ("r","y") and m["f30"][0]>=MIN_SPEND and (n7<3 or _rag(b7/n7,n7)!="g") and rk and rk["n"]>=2 and rk["rank"]>rk["n"]/2:
            return ("close","Close",f"30-day health {round(100*b30/n30)}%, ranked #{rk['rank']} of {rk['n']}")
        return None
    lb,ln=m["lh"]
    if ln>=5 and m["l"][0]>=50:
        lp=lb/ln; lrb,lrn=m["lr"]; lrt=f"{round(100*lrb/lrn)}%" if lrn>=3 else "too few days"
        if lp>=0.60: return ("reopen","Reopen",f"Lifetime {round(100*lp)}% of {ln} days under $4.50 (last run {lrt}). A weak last run may be seasonal.")
        if lp<0.35: return ("keep","Keep closed",f"Lifetime {round(100*lp)}% of {ln} days under $4.50 (last run {lrt}).")
    return None
for r in rows:
    r["m2"]=metrics(by[r["key"]],r["act"]); r["allsets"]=[]
    for aid,a in asd.get(r["key"],{}).items():
        am=metrics(a["days"],a["act"] and r["act"]); am["name"]=a["name"]; r["allsets"].append(am)
    _rk=rank_group({i:x for i,x in enumerate(r["allsets"]) if x["act"]})
    for i,x in enumerate(r["allsets"]): x["rank"]=_rk.get(i); x["sig"]=sig_for(x); x["flag"]=flag_for(x)
    finalize(r["allsets"])
    r["sets"]=[x for x in r["allsets"] if x["m"][0]>0 or (x["flag"] and x["flag"][0]=="reopen")]   # spend in last 30 days, or a reopen candidate
    r["sets"].sort(key=lambda x:(not x["act"],-x["m"][0],-x["l"][0]))
_rk=rank_group({i:r["m2"] for i,r in enumerate(rows) if r["act"]})
for i,r in enumerate(rows): r["m2"]["rank"]=_rk.get(i); r["m2"]["sig"]=sig_for(r["m2"]); r["m2"]["flag"]=flag_for(r["m2"])
finalize([r["m2"] for r in rows])
_go=[x for r in rows for x in [r["m2"]]+r["allsets"] if x.get("rr")]
if _go:
    _a=pctl({i:x["l"][1] for i,x in enumerate(_go)},True); _b=pctl({i:cpm(*x["l"]) for i,x in enumerate(_go)},False)
    for k,i in enumerate(sorted(range(len(_go)),key=lambda i:-(0.7*_a[i]+0.3*_b[i])),1): _go[i]["rr"]["g"]=k; _go[i]["rr"]["gn"]=len(_go)

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
    k={"Today":"t","Week":"w","15d":"x","Month":"m","Lifetime":"l"}[lab]
    s,m=cur; ps,pm=prev if prev and prev[0] else (None,None)
    if not s: return f'<td class="s1 c{k}" data-l="{lab} spend">—</td><td class="c{k}" data-l="{lab} msgs">—</td><td class="c{k}" data-l="{lab} cost/msg">—</td>'
    c=cpm(s,m)
    return (f'<td class="s1 c{k}" data-l="{lab} spend">{money(s)}{arrow(s,ps,None) if ps else ""}</td>'
            f'<td class="c{k}" data-l="{lab} msgs">{int(m):,}{arrow(m,pm,True) if pm is not None else ""}</td>'
            f'<td class="c{k}" data-l="{lab} cost/msg"><span class="p {band(c)}">{fcpm(c)}</span>{arrow(c,cpm(ps,pm),False) if ps else ""}</td>')
def hrag(p,n): return "n" if n<3 else ("g" if p>=0.60 else ("y" if p>=0.35 else "r"))
def hcell(m):
    if m["health"]==("none","Paused"):
        ch=""
        for cap,(b_,n_) in (("7 days",m["h7"]),("15 days",m["h15"]),("30 days",(m["hb"],m["hn"])),("Last run",m["lr"]),("Lifetime",m["lh"])):
            v=(f'<span class="hv {hrag(b_/n_,n_)}" title="{b_} of {n_} spend days under $4.50">{round(100*b_/n_)}%</span>' if n_>=3 else '<span class="hv n" title="Fewer than 3 days with spend">–</span>')
            ch+=f'<span class="hch"><span class="hcap">{cap}</span>{v}</span>'
        last=f'<span class="hlast">Paused. Last spend {m["ls"].strftime("%-d %b")}</span>' if m["ls"] else '<span class="hlast">Paused, no spend</span>'
        return f'<td class="s1 hc"><span class="hcs">{ch}</span>{last}</td>'
    chips=""
    for cap,(b_,n_) in (("7 days",m["h7"]),("15 days",m["h15"]),("30 days",(m["hb"],m["hn"])),("Current run",m["lr"]),("Lifetime",m["lh"])):
        if n_>=3: v=f'<span class="hv {hrag(b_/n_,n_)}" title="{b_} of {n_} spend days under $4.50">{round(100*b_/n_)}%</span>'
        else: v='<span class="hv n" title="Fewer than 3 days with spend">–</span>'
        chips+=f'<span class="hch"><span class="hcap">{cap}</span>{v}</span>'
    return f'<td class="s1 hc"><span class="hcs">{chips}</span></td>'
def rkcol(pos,n):
    if not pos or n<=1: return "n"
    if n==2: return "g" if pos==1 else "y"
    f=(pos-1)/(n-1)
    return "g" if f<=1/3 else ("r" if f>=2/3 else "y")
def rkrow(rk,adset):
    if rk is None: return '<span class="rkrow"><span class="rkl">Not ranked, under $20 spend</span></span>'
    ch=""
    for cap,k in (("7d","7"),("15d","15"),("30d","30")):
        pos=rk["r"+k]
        ch+=(f'<span class="rkc {rkcol(pos,rk["n"+k])}" title="Rank on the last {k} days alone, out of {rk["n"+k]}">{cap} #{pos}</span>' if pos else f'<span class="rkc n" title="Under $20 spend in this window">{cap} –</span>')
    return f'<span class="rkrow"><span class="rkl">Rank <b>#{rk["rank"]}</b> of {rk["n"]}</span>{ch}</span>'
def rkrow_p(m):
    r=m.get("rr")
    if not r: return ""
    ch="".join(f'<span class="rkc {rkcol(pos,r["n"])}" title="Rank among paused candidates on lifetime {t}, out of {r["n"]}">{cap} #{pos}</span>' for cap,pos,t in (("Msgs",r["mp"],"messages"),("Cost",r["cp"],"cost per message")))
    return f'<span class="rkrow"><span class="rkl">Reopen rank <b>#{r["k"]}</b> of {r["n"]}{f' · all paused #{r["g"]} of {r["gn"]}' if r.get("g") else ''}</span>{ch}</span>'
def sigrow(sg,fl=None):
    x=fl or sg
    return f'<span class="sigrow"><span class="sp {x[0]}" title="{html.escape(x[2])}">{x[1]}</span><small>{html.escape(x[2])}</small></span>' if x else ""
def prow(cls,name,m,attrs=""):
    return (f'<tr class="{cls}"{attrs}>{name}'+hcell(m)
            +trio(m["t"],m["pt"],"Today")+trio(m["w"],m["pw"],"Week")+trio(m["x"],m["px"],"15d")+trio(m["m"],m["pm"],"Month")+trio(m["l"],None,"Lifetime")+'</tr>')
trs=""; first_p=True
for i,r in enumerate(rows):
    cls="cp act" if r["act"] else "cp paused"
    if not r["act"] and first_p: cls+=" firstp"; first_p=False
    m=r["m2"]
    btn=(f'<button type="button" class="xp" aria-expanded="false" aria-label="Show ad sets">&#9656;</button>' if r["sets"] else '<span class="xp0"></span>')
    nm=(f'<th scope="row" title="Launched {r["L"].strftime("%-d %b %Y")} ({r["live"]} days ago)"><div class="nmrow">{btn}<span class="nmw"><span class="nm">{html.escape(r["n"])}</span>'
        f'<span class="meta"><span class="st {"on" if r["act"] else "off"}">{"Active" if r["act"] else "Paused"}</span>'+(f'<span class="ln2">{len(r["sets"])} ad sets</span>' if r["sets"] else "")+'</span>'
        +(sigrow(m.get("sig"),m.get("flag"))+rkrow(m.get("rank"),False) if r["act"] else sigrow(None,m.get("flag"))+rkrow_p(m))+'</span></div></th>')
    trs+='<tbody class="grp">'+prow(cls,nm,m,f' data-id="c{i}"')
    for x in r["sets"]:
        an=(f'<th scope="row" class="asn"><span class="nm">{html.escape(x["name"])}</span>'
            f'<span class="meta"><span class="st {"on" if x["act"] else "off"}">{"Active" if x["act"] else "Paused"}</span></span>'
            +(sigrow(x.get("sig"),x.get("flag"))+rkrow(x.get("rank"),True) if x["act"] else sigrow(None,x.get("flag"))+rkrow_p(x))+'</th>')
        trs+=prow("as"+("" if x["act"] else " paused"),an,x,f' data-p="c{i}" hidden')
    trs+='</tbody>'
trs+=('<tbody><tr class="total"><th scope="row">All non-tracked campaigns</th><td class="s1"></td>'+trio(tot["t"],tot["pt"],"Today")+trio(tot["w"],tot["pw"],"Week")+trio(tot["x"],tot["px"],"15d")
      +trio(tot["m"],tot["pm"],"Month")+trio(tot["l"],None,"Lifetime")+'</tr></tbody>')

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
DK="--bg:#0E1116;--card:#171B22;--ink:#EDEFF3;--muted:#A0A8B6;--line:#2A303B;--sub:#1F242D;--g:#6FD6A6;--gb:#123326;--gl:#27604A;--y:#F2C85B;--yb:#362A0E;--yl:#6B5419;--r:#FF8C80;--rb:#3D1A17;--rl:#7A3129;--t:#8FB2FF;--tb:#1A2B52;--tc:#141E36;--w:#C3A6FF;--wb:#2C2150;--wc:#1D1834;--m:#5FD4C6;--mb:#123D3A;--mc:#0F2927;--l:#FFB085;--lb:#43261A;--lc:#2C1B14;--x:#F0A6F5;--xb:#3E1F42;--xc:#2A1730;--camp-bg:#000000;--as-bg:#262B34"
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
<div class="tw"><table class="mini"><thead><tr><th></th><th class="ct">{LBL_T}</th><th class="cw">7 days</th><th class="cm">30 days</th><th class="cl">Lifetime</th></tr></thead><tbody>
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
--l:#9A3412;--lb:#FCE6D6;--lc:#FEF3EA;--x:#A21CAF;--xb:#F6DDF8;--xc:#FBF0FC;--camp-bg:#14161B;--as-bg:#EEF0F3}}
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
.s1{{border-left:1px solid var(--line)}}
td.ct,th.ct{{--pc:var(--t);--pb:var(--tb);--pcol:var(--tc)}}td.cw,th.cw{{--pc:var(--w);--pb:var(--wb);--pcol:var(--wc)}}
td.cx,th.cx{{--pc:var(--x);--pb:var(--xb);--pcol:var(--xc)}}td.cm,th.cm{{--pc:var(--m);--pb:var(--mb);--pcol:var(--mc)}}td.cl,th.cl{{--pc:var(--l);--pb:var(--lb);--pcol:var(--lc)}}
table.mini td.ct,table.mini td.cw,table.mini td.cx,table.mini td.cm,table.mini td.cl{{background:var(--pcol)}}
thead th.ct,thead th.cw,thead th.cx,thead th.cm,thead th.cl{{background:var(--pb);color:var(--pc)}}
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
tr.total td{{background:var(--sub);font-weight:700}}
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
@media (max-width:900px){{.two{{grid-template-columns:1fr}}
 main{{padding:16px 10px 40px}}.box{{padding:12px}}
 table.mini{{table-layout:fixed;width:100%}}
 table.mini th,table.mini td{{padding:8px 3px;font-size:12.5px}}
 table.mini thead th{{font-size:12px}}
 table.mini thead th:first-child,table.mini tbody th{{width:27%}}
 table.mini tbody th{{min-width:0;font-size:12px;line-height:1.25;white-space:normal;padding-left:2px}}
 table.mini .ar{{font-size:9px;margin-left:1px}}}}
.wrap table{{min-width:1560px}}
thead th.hcamp{{position:sticky;left:0;z-index:2;background:var(--card);vertical-align:bottom}}
thead th.hh{{vertical-align:bottom;text-align:left}}thead th.hh small{{display:block;font-weight:400;font-size:11.5px}}
.hc,.rc,.gc{{text-align:left;white-space:normal;min-width:130px}}.gc{{min-width:150px}}
.hc small,.rc small,.gc small{{display:block;color:var(--muted);font-size:12px;line-height:1.3;margin-top:2px}}
.hc b{{font-size:15px;margin-left:4px}}.rc b{{font-size:16px}}.rk0{{color:var(--muted)}}
.hp,.sp{{display:inline-block;padding:1px 9px;border-radius:99px;font-weight:700;font-size:12.5px;border:1px solid transparent}}
.hp.g,.sp.up{{background:var(--gb);color:var(--g);border-color:var(--gl)}}.hp.y,.sp.hold{{background:var(--yb);color:var(--y);border-color:var(--yl)}}
.hp.r,.sp.down{{background:var(--rb);color:var(--r);border-color:var(--rl)}}.hp.none{{background:var(--sub);color:var(--muted)}}
.xp,.xp0{{display:inline-block;width:22px;height:22px;margin-right:6px;vertical-align:top;flex:none}}
.xp{{border:1px solid var(--line);background:var(--sub);color:var(--ink);border-radius:6px;font-size:12px;line-height:1;cursor:pointer;padding:0}}
.xp:focus-visible{{outline:3px solid var(--t);outline-offset:2px}}
tr.cp.open .xp{{transform:rotate(90deg)}}tr.cp{{cursor:pointer}}
tr.cp .nmrow{{display:flex;align-items:flex-start}}tr.cp .nmw{{display:block;min-width:0}}
tr.cp .nm{{font-weight:700;font-size:15.5px}}
tr.as>th.asn{{padding-left:30px}}tr.as .nm{{font-size:13.5px;font-weight:500}}tr.as .nm:before{{content:"↳ ";color:var(--muted)}}
tr.as>td{{font-size:13.5px}}tr.as+tr.as{{border-top:1px solid var(--line)}}
.hws{{display:flex;flex-wrap:wrap;gap:2px 10px;margin-top:4px}}.hw{{font-size:12px;color:var(--muted);white-space:nowrap}}.hw i{{font-style:normal}}.hw b{{color:var(--ink);font-weight:700}}
.how{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 12px;font-size:13.5px}}
.how summary{{cursor:pointer;font-weight:600}}.how dl{{margin:8px 0 0;display:grid;grid-template-columns:max-content 1fr;gap:6px 14px}}.how dt{{font-weight:700}}.how dd{{margin:0;color:var(--muted)}}
.hint{{display:none;margin:0 0 8px;font-size:12.5px;color:var(--muted)}}
@media (max-width:900px){{.hint{{display:block}}.how dl{{grid-template-columns:1fr}}}}
.foot{{color:var(--muted);font-size:13px;margin:12px 2px 0;max-width:80ch}}
@media (max-width:900px){{header{{flex-direction:column}} tbody th{{min-width:140px;max-width:140px;padding:10px 8px}} thead th.hcamp small{{display:none!important}}
 tbody th .nm{{font-size:13.5px;line-height:1.25}} tbody th .meta{{font-size:11.5px}} .ln{{display:none}} .xp,.xp0{{width:20px;height:20px;margin-right:5px}} tr.as th.asn{{padding-left:20px}}}}
.ln2{{margin-left:4px;white-space:nowrap}}.ln+.ln2:before{{content:" · "}}
@media (max-width:900px){{.ln+.ln2:before{{content:""}}}}

.wrapx{{position:relative}}
.wrapx .wrap{{max-height:calc(100vh - 72px);max-height:calc(100dvh - 72px);overflow:auto;overscroll-behavior:contain}}
.wrap>.jump{{position:sticky;top:0;left:0;width:100%;box-sizing:border-box;margin:0;padding:8px 10px;z-index:7;border-bottom:1px solid var(--line)}}
.wrapx thead th{{position:sticky;top:var(--jh,0px);z-index:3;box-shadow:0 1px 0 var(--line)}}.wrapx thead tr+tr th{{z-index:3}}
.wrapx thead th.hcamp{{z-index:6}}
.wrapx thead th.hh{{background:var(--card)}}
.wrapx tbody tr.cp.open{{border-top:0!important}}
.wrapx tbody tr.cp.open>td{{position:sticky;top:var(--hh,84px);z-index:2;box-shadow:0 2px 0 var(--line)}}.wrapx tbody tr.cp.open>th{{top:var(--hh,84px);z-index:4}}
@media(max-width:640px){{.wrapx tbody tr.cp.open>th .rkrow,.wrapx tbody tr.cp.open>th .sigrow small{{display:none}}}}
.wrapx:after{{content:"›";position:absolute;right:8px;top:50%;width:30px;height:30px;margin-top:-15px;border-radius:50%;background:var(--ink);color:var(--bg);font:700 22px/28px Figtree,sans-serif;text-align:center;pointer-events:none;opacity:0;transition:opacity .2s;box-shadow:0 2px 8px rgba(0,0,0,.35)}}
.wrapx.mr:after{{opacity:.9}}
.jump{{position:sticky;top:env(safe-area-inset-top,0px);z-index:6;display:flex;gap:6px;align-items:center;background:var(--bg);padding:8px 0;margin:0 0 6px;overflow-x:auto}}
.jump button{{font:600 13px Figtree,sans-serif;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:99px;padding:6px 13px;cursor:pointer;white-space:nowrap;flex:none}}
.jump button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.jump .stp{{padding:6px 11px;font-size:16px;line-height:1}}
.jump button:focus-visible{{outline:3px solid var(--t);outline-offset:2px}}
tbody tr.cp{{--ink:#F3F4F6;--muted:#A9B0BC;--g:#6FD6A6;--gb:#123326;--gl:#27604A;--y:#F2C85B;--yb:#362A0E;--yl:#6B5419;--r:#FF8C80;--rb:#3D1A17;--rl:#7A3129;--line:#2E333D;--sub:#262B34;--card:#14161B;color:var(--ink);border-top:0!important}}
tbody tr.cp>th,tbody tr.cp>td{{background:var(--camp-bg);color:var(--ink)}}
tbody tr.as>th,tbody tr.as>td{{background:var(--as-bg)}}
tbody tr.cp.paused>th,tbody tr.cp.paused>td{{background:var(--camp-bg)}}
tbody tr.cp>th{{box-shadow:inset 8px 0 0 #1B7F5C}}tbody tr.cp.paused>th{{box-shadow:inset 8px 0 0 #7C8494}}
tbody tr.cp>th .nm{{padding-left:2px}}
tbody tr.cp .xp{{background:#fff;color:#14161B;border-color:#fff;font-weight:700}}
tbody tr.cp.paused .xp{{background:#C9CED8;border-color:#C9CED8}}
tbody tr.cp:not(.firstp){{border-top:6px solid var(--bg)!important}}
tbody tr.as>th{{box-shadow:inset 3px 0 0 #5FBF9A}}tbody tr.as.paused>th{{box-shadow:inset 3px 0 0 #B3BAC6}}
tbody tr.as.paused>th,tbody tr.as.paused>td{{background:repeating-linear-gradient(135deg,var(--as-bg) 0 9px,color-mix(in srgb,var(--as-bg) 90%,var(--muted)) 9px 10px)}}
tbody tr.as:last-of-type>th,tbody tr.as:last-of-type>td{{border-bottom:2px solid var(--muted)}}
tbody th{{min-width:340px;max-width:370px}}
.hc{{min-width:214px;text-align:left;white-space:nowrap}}
.hcs{{display:flex;gap:10px;justify-content:flex-start}}
.hch{{display:flex;flex-direction:column;align-items:center;gap:3px}}.hcap{{font-size:11.5px;color:var(--muted)}}
.hv{{display:inline-block;min-width:56px;text-align:center;padding:2px 8px;border-radius:7px;font-weight:700;font-size:14px;border:1px solid transparent}}
.hv.g,.rkc.g{{background:var(--gb);color:var(--g);border-color:var(--gl)}}.hv.y,.rkc.y{{background:var(--yb);color:var(--y);border-color:var(--yl)}}
.hv.r,.rkc.r{{background:var(--rb);color:var(--r);border-color:var(--rl)}}.sp.close{{background:#C62828;color:#fff;border-color:#C62828}}.sp.reopen{{background:#1B7F5C;color:#fff;border-color:#1B7F5C}}.sp.keep{{background:var(--sub);color:var(--muted);border-color:var(--line)}}
.hlast{{display:block;margin-top:5px;font-size:11.5px;color:var(--muted)}}
.hv.n,.rkc.n{{background:var(--sub);color:var(--muted);border-color:var(--line)}}
.sigrow,.rkrow{{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;margin-top:6px}}
.sigrow small{{color:var(--muted);font-size:12px;line-height:1.3;flex:1 1 100px}}
.rkl{{font-size:12.5px;color:var(--muted);margin-right:2px}}.rkl b{{color:var(--ink)}}
.rkc{{font-size:12px;font-weight:700;padding:1px 7px;border-radius:6px;border:1px solid transparent;white-space:nowrap}}
@media (max-width:900px){{tbody th{{width:148px;min-width:148px;max-width:148px;padding:10px 7px;overflow-wrap:anywhere}}.nmrow,.nmw{{min-width:0}}.ln2{{white-space:normal}}.hc{{min-width:190px}}
 tbody th .nm{{font-size:13px}}.sigrow small{{display:none}}.rkl{{font-size:11.5px}}.rkc{{font-size:11px;padding:0 5px}}
 tbody td{{padding:10px 4px;font-size:13.5px}}td .p{{padding:1px 5px}}.st{{font-size:11px;padding:0 6px}}.hv{{min-width:48px;font-size:13px;padding:2px 5px}}.hcap{{font-size:11px}}.hcs{{gap:6px}}
 thead th{{padding:8px 3px}}tbody td{{padding:10px 3px}}td .ar{{margin-left:2px}}td .p{{font-size:13px}}.wrapx{{margin:0 -10px}}.wrap{{border-radius:0;border-left:0;border-right:0}}tbody th{{width:140px;min-width:140px;max-width:140px}}}}
@media (max-width:420px){{tbody th{{width:128px;min-width:128px;max-width:128px}}}}
</style></head><body><main>
<header><div class="hd"><h1>Non-tracked campaigns, daily</h1><p>Webirox ad account, Meta messaging campaigns. Report for {TODAY.strftime("%A %-d %B %Y")}, updated {NOW.strftime("%-I:%M %p")} Sydney time.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
<section class="kpis">
{kpi("t",LBL_T,TODAY.strftime("%a %-d %b %Y"),tot["t"],tot["pt"],"Arrows compare with the day before, "+YEST.strftime("%a %-d %b")+("." if TODAY<REAL else ". Today is still in progress."),SP["t"])}
{kpi("w","Last 7 days",W7.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b %Y"),tot["w"],tot["pw"],"Arrows compare with the 7 days before, "+(W7-D(7)).strftime("%-d %b")+" to "+(W7-D(1)).strftime("%-d %b")+".",SP["w"])}
{kpi("m","Last 30 days",M30.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b %Y"),tot["m"],tot["pm"],"Arrows compare with the 30 days before, "+(M30-D(30)).strftime("%-d %b")+" to "+(M30-D(1)).strftime("%-d %b")+".",SP["m"])}
{kpi("l","Lifetime",dt.date.fromisoformat(FIRST).strftime("%-d %b %Y")+" to "+TODAY.strftime("%-d %b %Y"),tot["l"],None,f"All {len(rows)} non-tracked campaigns, active and paused, from the first day of spend. Sales are only recorded from {TF.strftime('%-d %b %Y')}, when order sources started being filled in, so lifetime ROAS is understated.",SP["l"],f'<p class="kn2">ROAS since {TF.strftime("%-d %b %Y")}: <b>{roasf(roas_tf)}</b> ({money(sales_l)} sales on {money(spend_since_tf)} spend)</p>')}
</section>
{SECTION}
<details class="how"><summary>How to read health, rank and spend signal</summary><dl>
<dt>Health</dt><dd>Share of days with spend where each message cost under $4.50, for the last 7, 15 and 30 full days. Green is 60% or more, amber 35 to 59%, red under 35% (a window with fewer than 3 spend days shows a dash). Hover a figure to see the day count.</dd>
<dt>Rank</dt><dd>Under each campaign name. Overall rank among active campaigns (ad sets rank inside their campaign), then the rank on 7, 15 and 30 days alone. Score is 70% messages received plus 30% cost per message; the overall number blends 30 days (60%) and 7 days (40%). Green is the top third, red the bottom third; under $20 spend in a window is not ranked.</dd>
<dt>Flags</dt><dd><b>Close #1</b> (active): 30-day health is red or amber, 7-day health is not green, at least $20 spent in 30 days, and it ranks in the bottom half of its group. #1 is the worst. <b>Reopen #1</b> (paused): lifetime health is green over at least 5 spend days and $50 spent, so a weak last run may just have been a bad season. Ranked best first (inside its group, and across all paused rows) on lifetime messages (70%) and lifetime cost per message (30%), inside its group. <b>Keep closed</b> (paused): lifetime health is red on the same evidence. Paused rows show 7, 15 and 30 day health too (blank if it did not spend), plus Last run (its latest stretch of spending, no gap over 3 days) and Lifetime.</dd>
<dt>Spend signal</dt><dd>Spend more when 30-day health is Good and the 7-day cost per message is at or below the 30-day figure. Spend less when health is Poor or the 7-day cost per message is over $6. Otherwise Hold.</dd></dl></details>
<p class="key"><button class="tg" id="xa" type="button" data-o="0">Expand all ad sets</button><span class="p g">Under $4.50</span><span class="p y">$4.50 to $6</span><span class="p r">Over $6</span><span>▲▼ change vs the previous period: green is better, red is worse, grey is spend</span></p>
<div class="wrapx"><div class="wrap"><nav class="jump" aria-label="Jump to a period"><button type="button" class="stp" data-step="-1" aria-label="Previous">&#8249;</button><button type="button" data-i="0">Health</button><button type="button" data-i="1">{LBL_T}</button><button type="button" data-i="2">7 days</button><button type="button" data-i="3">15 days</button><button type="button" data-i="4">30 days</button><button type="button" data-i="5">Lifetime</button><button type="button" class="stp" data-step="1" aria-label="Next">&#8250;</button></nav><table>
<thead><tr><th rowspan="2" class="hcamp">Campaign</th><th rowspan="2" class="s1 hh">Health<small>% of days under $4.50. Run = latest stretch of spend, no gap over 3 days</small></th><th colspan="3" class="s1 gh ct">{LBL_T}<small>{TODAY.strftime("%a %-d %b")}</small></th><th colspan="3" class="s1 gh cw">Last 7 days<small>{W7.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cx">Last 15 days<small>{M15.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cm">Last 30 days<small>{M30.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cl">Lifetime<small>Since {dt.date.fromisoformat(FIRST).strftime("%-d %b %Y")}</small></th></tr>
<tr>{"".join(f'<th class="s1 c{k}">Spend</th><th class="c{k}">Msgs</th><th class="c{k}">Cost/msg</th>' for k in "twxml")}</tr></thead>
{trs}</table></div></div>
<p class="foot">Messages are Meta "messaging conversations started". Periods end on {TODAY.strftime("%-d %b")}; arrows compare each period with the one before it. Health, rank and signal use completed days only. Ad sets shown are those with spend in the last 30 days.</p>
</main>
<script>
(function(){{var r=document.documentElement,b=document.getElementById('tg');
function cur(){{var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}}
function lab(){{b.textContent=cur()==='dark'?'Light mode':'Dark mode'}}
try{{var s=localStorage.getItem('ntr-theme');if(s)r.setAttribute('data-theme',s)}}catch(e){{}}
lab();b.addEventListener('click',function(){{var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{{localStorage.setItem('ntr-theme',n)}}catch(e){{}}lab()}});}})();
</script>
<script>
(function(){{var rows=document.querySelectorAll('tr.cp');var xa=document.getElementById('xa');
function set(tr,o){{tr.classList.toggle('open',o);var b=tr.querySelector('.xp');if(b)b.setAttribute('aria-expanded',o);
document.querySelectorAll('tr.as[data-p="'+tr.getAttribute('data-id')+'"]').forEach(function(a){{a.hidden=!o}})}}
rows.forEach(function(tr){{if(!tr.querySelector('.xp'))return;tr.addEventListener('click',function(){{set(tr,!tr.classList.contains('open'))}})}});
if(xa)xa.addEventListener('click',function(){{var open=xa.getAttribute('data-o')!=='1';rows.forEach(function(tr){{if(tr.querySelector('.xp'))set(tr,open)}});xa.setAttribute('data-o',open?'1':'0');xa.textContent=open?'Collapse all ad sets':'Expand all ad sets'}});}})();
</script>
<script>
(function(){{var _r=document.querySelector('tr.cp'),wrap=_r?_r.closest('.wrap'):null,bar=document.querySelector('.jump');if(!wrap||!bar)return;var box=wrap.parentNode;
var heads=[].slice.call(wrap.querySelectorAll('thead th.gh, thead th.hh'));
function stk(){{var r=wrap.querySelectorAll('thead tr');if(r.length>1){{var jh=bar.getBoundingClientRect().height,h=r[0].getBoundingClientRect().height;wrap.style.setProperty('--jh',jh+'px');r[1].querySelectorAll('th').forEach(function(t){{t.style.top=(jh+h)+'px'}});wrap.style.setProperty('--hh',(jh+h+r[1].getBoundingClientRect().height)+'px')}}}}stk();window.addEventListener('resize',stk);window.addEventListener('load',stk);if(window.ResizeObserver)new ResizeObserver(stk).observe(wrap.querySelector('thead'));
function sw(){{var h=wrap.querySelector('thead th.hcamp');return h?h.getBoundingClientRect().width:0}}
function left(el){{return el.getBoundingClientRect().left-wrap.getBoundingClientRect().left+wrap.scrollLeft}}
function go(i){{var el=heads[i];if(!el)return;wrap.scrollTo({{left:Math.max(0,left(el)-sw()-2),behavior:'smooth'}})}}
var btns=[].slice.call(bar.querySelectorAll('button[data-i]'));
function cur(){{var sl=wrap.scrollLeft+sw(),best=0,bd=1e9;heads.forEach(function(h,i){{var d=Math.abs(left(h)-sl);if(d<bd){{bd=d;best=i}}}});return best}}
function upd(){{var c=cur();btns.forEach(function(b){{b.classList.toggle('on',+b.getAttribute('data-i')===c)}});box.classList.toggle('mr',wrap.scrollLeft+wrap.clientWidth<wrap.scrollWidth-4)}}
btns.forEach(function(b){{b.addEventListener('click',function(){{go(+b.getAttribute('data-i'))}})}});
bar.querySelectorAll('button[data-step]').forEach(function(b){{b.addEventListener('click',function(){{go(Math.min(heads.length-1,Math.max(0,cur()+(+b.getAttribute('data-step')))))}})}});
wrap.addEventListener('scroll',upd,{{passive:true}});window.addEventListener('resize',upd);upd();}})();
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
LAB={"t":(LBL_T,TODAY.strftime("%-d %b")),"w":("Last 7 days",W7.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b")),"m":("Last 30 days",M30.strftime("%-d %b")+" to "+TODAY.strftime("%-d %b")),"l":("Lifetime","Since "+dt.date.fromisoformat(FIRST).strftime("%-d %b %Y"))}
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
<tr><th style="{TH}">Campaign</th><th style="background:{PC["t"][1]};color:{PC["t"][0]};padding:8px 10px;text-align:right">{LBL_T}</th><th style="background:{PC["m"][1]};color:{PC["m"][0]};padding:8px 10px;text-align:right">30 days</th><th style="background:{PC["l"][1]};color:{PC["l"][0]};padding:8px 10px;text-align:right">Lifetime</th><th style="{TH}">Under $4.50</th></tr>
{crow}</table>
<h3 style="margin:18px 0 6px">Orders to attribute</h3>
{elist(u48,"Last 48 hours")}{elist(u7,"3 to 7 days ago")}
<p style="margin:4px 0;font-size:12px;color:#5A6272">Older backlog since {TF.strftime("%-d %b %Y")}: {len(uold)} paid orders, {money(sum(u[2] for u in uold))}.</p>
{btn}</div>'''
if EMAIL: open(EMAIL,"w").write(email)
p=PR["m"]; t=PR["t"]
worst=max((r for r in act if r["t"][0]),key=lambda r:cpm(*r["t"]) if r["t"][1] else 1e9,default=None)
_D14=[(TODAY-D(13-i)).isoformat() for i in range(14)]
def _r7(k):
    ks=[(dt.date.fromisoformat(k)-D(j)).isoformat() for j in range(7)]
    s_=sum(spd.get(x,0) for x in ks); return round(sum(rvd.get(x,0) for x in ks)/s_,2) if s_ else 0
SPARK=[[round(spd.get(k,0),2) for k in _D14],[msd.get(k,0) for k in _D14],[round(rvd.get(k,0),2) for k in _D14],[_r7(k) for k in _D14]]
if os.environ.get("SUMMARY_DIR"):
    json.dump(dict(spark=SPARK,updated=NOW.strftime("%-d %b %Y, %-I:%M %p"),today_date=TODAY.strftime("%-d %b"),t_label=LBL_T.lower(),t_s=t["s"],t_m=t["m"],t_cpm=cpm(t["s"],t["m"]) if t["m"] else None,
                   m_s=p["s"],m_sales=p["sv"],m_roas=p["r"],m_cpm=cpm(p["s"],p["m"]),active=len(act),
                   unatt=len(u48)+len(u7),sig=RS["code"],sig_label=SIG[1],reason=SIG[2]),open(os.path.join(os.environ["SUMMARY_DIR"],"daily.json"),"w"))
print("PUSH: "+f"Non-tracked {TODAY.strftime('%-d %b')} | {LBL_T} ${t['s']:.0f}, {int(t['m'])} msgs, {fcpm(cpm(t['s'],t['m']))}/msg, FB sales {money(t['sv']) if t['sv'] else '$0'} | 30-day ROAS {roasf(p['r'])} | {SIG[1]}"+(f" | {len(u48)+len(u7)} orders need a source" if (u48 or u7) else ""))
