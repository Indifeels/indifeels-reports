"""Facebook TRACKED campaigns report builder.

Same layout, look and feel, health / rank / flag / signal logic as build.py (the Facebook non-tracked report),
but the success measure is real tracked sales (Meta purchase events with value) instead of messages.
Usage: python3 fb_tracked.py DATA_DIR OUT_HTML
DATA_DIR holds windsor*.json: Windsor facebook rows with
  date,campaign,campaign_id,campaign_status,campaign_start_time,spend,impressions,clicks,link_clicks,reach,
  actions_purchase,action_values_purchase,actions_add_to_cart,actions_initiate_checkout,actions_landing_page_view
Only campaigns with "tracked" in the name (and not "non tracked") are used.
"""
import json, html, datetime as dt, sys, glob, os, re
from zoneinfo import ZoneInfo
S = sys.argv[1]; OUT = sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("Australia/Sydney"); NOW = dt.datetime.now(TZ)
if os.environ.get("REPORT_NOW"): NOW = dt.datetime.fromisoformat(os.environ["REPORT_NOW"]).astimezone(TZ)
TODAY = NOW.date(); D = dt.timedelta
YEST = TODAY - D(1)
REAL = dt.datetime.now(TZ).date()
LBL_T = "Today" if TODAY >= REAL else ("Yesterday" if TODAY == REAL - D(1) else TODAY.strftime("%A"))
FULL_END = TODAY if TODAY < REAL else TODAY - D(1)      # last fully completed day

# ---- settings (same defaults as the non-tracked report where they apply) ----
CONTRIB = 0.75 / 1.1                       # revenue left after GST (1/11) and product cost (25% of ex-GST revenue)
BE_ROAS = 1 / CONTRIB                      # break-even ROAS, 1.47x: below this an order loses money
TARGET_ROAS = float(os.environ.get("TARGET_ROAS", "2.0"))   # a "good" day: ROAS at or above this
MIN_SPEND = 20.0; MIN_SPEND_1 = 5.0        # spend floors for ranking (30/7 day windows, single day)

# ---- data ----
# vector per campaign-day: 0 spend, 1 impressions, 2 clicks(all), 3 link clicks, 4 reach, 5 purchases, 6 purchase value, 7 add to cart, 8 checkouts, 9 landing page views
KEYS = ["spend", "impressions", "clicks", "link_clicks", "reach", "actions_purchase", "action_values_purchase", "actions_add_to_cart", "actions_initiate_checkout", "actions_landing_page_view"]
def unwrap(x):
    if isinstance(x, dict) and "result" in x: x = x["result"]
    if isinstance(x, dict) and "data" in x and isinstance(x["data"], list): x = x["data"]
    if isinstance(x, str): return unwrap(json.loads(x))
    return x
def is_tracked(n):
    n = (n or "").lower().replace("-", " ")
    return "tracked" in n and "non tracked" not in n
raw = {}
for f in sorted(glob.glob(f"{S}/windsor*")):
    for r in unwrap(json.load(open(f))):
        if is_tracked(r.get("campaign")): raw[(r["date"], r["campaign"])] = r
if not raw: raise SystemExit("No tracked Meta campaign rows found")
by = {}; meta = {}
for r in sorted(raw.values(), key=lambda r: r["date"]):
    v = [float(r.get(k) or 0) for k in KEYS]
    if not v[0] and not v[5]: continue
    by.setdefault(r["campaign"], {})[r["date"]] = v
    meta[r["campaign"]] = (r.get("campaign_status") or "", (r.get("campaign_start_time") or r["date"])[:10])

def add(a, b): return [x + y for x, y in zip(a, b)]
def rng(days, a, b):
    out = [0.0] * 10
    for d, v in days.items():
        if str(a) <= d <= str(b): out = add(out, v)
    return out
# derived metrics from a vector
def roas(v): return v[6] / v[0] if v[0] else None
def sales(v): return v[6]
def orders(v): return v[5]
def profit(v): return v[6] * CONTRIB - v[0]
def cpa(v): return v[0] / v[5] if v[5] else None
def lctr(v): return v[3] / v[1] if v[1] else None
def lcpc(v): return v[0] / v[3] if v[3] else None
def cpm_(v): return v[0] / v[1] * 1000 if v[1] else None
def convr(v): return v[5] / v[3] if v[3] else None
def aov(v): return v[6] / v[5] if v[5] else None
def lpvr(v): return v[9] / v[3] if v[3] else None
def atcr(v): return v[7] / v[9] if v[9] else None
def icr(v): return v[8] / v[7] if v[7] else None
def pcr(v): return v[5] / v[8] if v[8] else None

def band(r): return "none" if r is None else "g" if r >= TARGET_ROAS else "b" if r >= BE_ROAS else "r"
def roasf(r): return "—" if r is None else f"{r:.2f}x"
def money(v): return "—" if not v else (f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}")
def money0(v): return ("−" if v < 0 else "") + f"${abs(v):,.0f}"
def pct(v, d=1): return "—" if v is None else f"{v*100:.{d}f}%"
def num(v): return f"{int(round(v)):,}"
def arrow(now, prev, higher_good):
    if now is None or prev is None or now == prev: return ""
    up = now > prev; cls = "nt" if higher_good is None else ("gd" if up == higher_good else "bd")
    return f'<i class="ar {cls}" title="{"Up" if up else "Down"} vs previous period">{"▲" if up else "▼"}</i>'

W7 = TODAY - D(6); M15 = TODAY - D(14); M30 = TODAY - D(29)
P = {"t": (TODAY, TODAY, YEST, YEST), "w": (W7, TODAY, W7 - D(7), W7 - D(1)), "x": (M15, TODAY, M15 - D(15), M15 - D(1)), "m": (M30, TODAY, M30 - D(30), M30 - D(1))}
H30 = (FULL_END - D(29), FULL_END); H15 = (FULL_END - D(14), FULL_END); H7 = (FULL_END - D(6), FULL_END)

def good_day(v): return v[0] > 0 and (v[6] / v[0]) >= TARGET_ROAS
def metrics(days, act):
    m = {}
    for k, (a, b, pa, pb) in P.items(): m[k] = rng(days, a, b); m["p" + k] = rng(days, pa, pb)
    m["l"] = rng(days, "0000", "9999")
    m["f30"] = rng(days, *H30); m["f15"] = rng(days, *H15); m["f7"] = rng(days, *H7); m["f1"] = rng(days, FULL_END, FULL_END)
    sp = [d for d in days if days[d][0] > 0 and str(H30[0]) <= d <= str(H30[1])]
    m["hn"] = len(sp); m["hb"] = sum(1 for d in sp if good_day(days[d])); m["act"] = act
    def _hw(h):
        d_ = [d for d in days if days[d][0] > 0 and str(h[0]) <= d <= str(h[1])]
        return (sum(1 for d in d_ if good_day(days[d])), len(d_))
    m["h7"] = _hw(H7); m["h15"] = _hw(H15)
    allsp = sorted(d for d in days if days[d][0] > 0 and d <= str(FULL_END))
    m["lh"] = (sum(1 for d in allsp if good_day(days[d])), len(allsp))
    if allsp:
        m["ls"] = dt.date.fromisoformat(allsp[-1]); _lr = [allsp[-1]]
        for d in reversed(allsp[:-1]):
            if (dt.date.fromisoformat(_lr[-1]) - dt.date.fromisoformat(d)).days > 3: break
            _lr.append(d)
        m["lr"] = (sum(1 for d in _lr if good_day(days[d])), len(_lr))
    else: m["ls"] = None; m["lr"] = (0, 0)
    _all = sorted(d for d in days if days[d][0] > 0)
    if _all:
        m["first"] = dt.date.fromisoformat(_all[0]); _rs = _all[-1]
        for d in reversed(_all[:-1]):
            if (dt.date.fromisoformat(_rs) - dt.date.fromisoformat(d)).days > 3: break
            _rs = d
        m["rs"] = dt.date.fromisoformat(_rs)
    else: m["first"] = m["rs"] = None
    s30 = m["f30"][0]; o30 = m["f30"][5]
    if not act: m["health"] = ("none", "Paused")
    elif m["hn"] < 3: m["health"] = ("none", "New")
    else:
        p_ = m["hb"] / m["hn"]
        m["health"] = ("r", "Poor") if (p_ < 0.35 or (s30 > 0 and not o30)) else (("g", "Good") if p_ >= 0.60 else ("y", "Watch"))
    return m

def pctl(vals, higher_good):
    ids = list(vals); n = len(ids)
    if n == 1: return {ids[0]: 1.0}
    out = {}
    for i in ids:
        worse = sum(1 for j in ids if j != i and ((vals[j] < vals[i]) if higher_good else (vals[j] > vals[i])))
        tie = sum(1 for j in ids if j != i and vals[j] == vals[i])
        out[i] = (worse + 0.5 * tie) / (n - 1)
    return out
def _score(el):
    a = pctl({i: v[6] for i, v in el.items()}, True); b = pctl({i: (roas(v) or 0) for i, v in el.items()}, True)
    return {i: 0.7 * a[i] + 0.3 * b[i] for i in el}
def rank_group(ms):
    """Score = 70% tracked sales + 30% ROAS (each as a percentile among peers). Final = 60% last 30 days + 40% last 7 days (full days)."""
    def score(win, floor=MIN_SPEND):
        el = {i: v[win] for i, v in ms.items() if v[win][0] >= floor}
        return _score(el) if el else {}
    s30 = score("f30"); s15 = score("f15"); s7 = score("f7"); s1 = score("f1", MIN_SPEND_1)
    fin = {i: (0.6 * s30[i] + 0.4 * s7[i] if i in s7 else s30[i]) for i in s30}
    order = sorted(fin, key=lambda i: (-fin[i], -ms[i]["f30"][6]))
    srt = lambda sc, w: sorted(sc, key=lambda i: (-sc[i], -ms[i][w][6]))
    o15 = srt(s15, "f15"); o7 = srt(s7, "f7"); o30 = srt(s30, "f30"); o1 = srt(s1, "f1")
    return {i: dict(rank=order.index(i) + 1, n=len(order), r7=(o7.index(i) + 1 if i in s7 else None), r15=(o15.index(i) + 1 if i in s15 else None), r30=o30.index(i) + 1, r1=(o1.index(i) + 1 if i in s1 else None), n1=len(o1), n7=len(o7), n15=len(o15), n30=len(o30)) for i in order}
def period_ranks(ms):
    out = {i: {} for i in ms}
    for k, w in (("1", "t"), ("7", "w"), ("15", "x"), ("30", "m")):
        el = {i: v[w] for i, v in ms.items() if v[w][0] > 0}
        if not el: continue
        sc = _score(el); order = sorted(sc, key=lambda i: (-sc[i], -el[i][6]))
        for pos, i in enumerate(order, 1): out[i]["r" + k] = pos; out[i]["n" + k] = len(order)
    return out

def diagnose(m):
    """Biggest leaks in the funnel for the last 7 full days (or 30 if 7 is too thin). Returns (window label, [(severity, tag, text)])."""
    v = m["f7"] if m["f7"][3] >= 60 and m["f7"][0] >= MIN_SPEND else m["f30"]
    lab = "7 days" if v is m["f7"] else "30 days"
    if v[3] < 40 or v[0] < MIN_SPEND: return lab, None
    iss = []
    def chk(val, bench, below, tag, text):
        if val is None: return
        ratio = val / bench if below else bench / val
        if ratio < 1: iss.append((ratio, tag, text))
    chk(lctr(v), 0.010, True, "Creative", f"Link CTR {pct(lctr(v))} is under 1%: the ad is not earning clicks (hook, image or offer).")
    chk(lcpc(v), 1.00, False, "Audience", f"Link clicks cost ${lcpc(v):.2f}, over $1.00: audience too narrow or crowded, or creative weak.") if lcpc(v) else None
    chk(lpvr(v), 0.70, True, "Landing page", f"Only {pct(lpvr(v),0)} of link clicks load the page: slow site or accidental clicks.")
    chk(atcr(v), 0.10, True, "Targeting / offer", f"Only {pct(atcr(v),1)} of visitors add to cart: product, price or audience intent does not match.")
    chk(icr(v), 0.30, True, "Cart", f"Only {pct(icr(v),0)} of carts reach checkout: price shock or shipping cost.")
    chk(pcr(v), 0.25, True, "Checkout", f"Only {pct(pcr(v),0)} of checkouts become orders: payment or shipping friction.")
    if v[5] and roas(v) is not None and roas(v) < BE_ROAS and aov(v) and not [i for i in iss if i[0] < 0.6]:
        iss.append((0.9, "Order value", f"Orders convert but average order {money(aov(v))} is too low for a {roasf(roas(v))} ROAS: push bundles or higher-value items."))
    if not v[5] and v[0] >= 40:
        iss.append((0.3, "No sales", f"{money(v[0])} spent over {lab} with no purchases."))
    iss.sort(key=lambda x: x[0])
    return lab, iss[:3]

def sig_for(m):
    if not m["act"]: return None
    (s30, o30), (s7, o7) = (m["f30"][0], m["f30"][5]), (m["f7"][0], m["f7"][5])
    if s30 < MIN_SPEND and s7 < MIN_SPEND: return ("hold", "Hold", "Too little spend to judge yet")
    r7 = roas(m["f7"]) if s7 else None; r30 = roas(m["f30"]) if s30 else None
    if m["health"][0] == "r": return ("down", "Spend less", "Health is poor")
    if r7 is not None and r7 < BE_ROAS: return ("down", "Spend less", "7 days of spend, no sales" if not m["f7"][5] else f"7-day ROAS {roasf(r7)} is under break-even {roasf(BE_ROAS)}")
    if m["health"][0] == "g" and r7 is not None and r30 is not None and r7 >= r30 and r7 >= TARGET_ROAS: return ("up", "Spend more", f"7-day ROAS {roasf(r7)} is at or above 30-day {roasf(r30)}")
    return ("hold", "Hold", "Not clearly better or worse")
def _rag(p, n): return "n" if n < 3 else ("g" if p >= 0.60 else ("y" if p >= 0.35 else "r"))
def flag_for(m):
    """Active: Close = 30-day health Poor/Watch, 7-day health not Good, >= $20 spent in 30 days, ranked in the bottom half.
    Paused: Reopen = lifetime health Good over >= 5 spend days and >= $50 spend; Keep closed = lifetime health Poor on the same evidence."""
    if m["act"]:
        b30, n30 = m["hb"], m["hn"]; b7, n7 = m["h7"]; rk = m.get("rank")
        if n30 >= 3 and _rag(b30 / n30, n30) in ("r", "y") and m["f30"][0] >= MIN_SPEND and (n7 < 3 or _rag(b7 / n7, n7) != "g") and rk and rk["n"] >= 2 and rk["rank"] > rk["n"] / 2:
            return ("close", "Close", f"30-day health {round(100*b30/n30)}%, ranked #{rk['rank']} of {rk['n']}")
        return None
    lb, ln = m["lh"]
    if ln >= 5 and m["l"][0] >= 50:
        lp = lb / ln; lrb, lrn = m["lr"]; lrt = f"{round(100*lrb/lrn)}%" if lrn >= 3 else "too few days"
        if lp >= 0.60: return ("reopen", "Reopen", f"Lifetime {round(100*lp)}% of {ln} days at {TARGET_ROAS:.1f}x or better (last run {lrt}). A weak last run may be seasonal.")
        if lp < 0.35: return ("keep", "Keep closed", f"Lifetime {round(100*lp)}% of {ln} days at {TARGET_ROAS:.1f}x or better (last run {lrt}).")
    return None
def finalize(ents):
    cl = [x for x in ents if x.get("flag") and x["flag"][0] == "close"]
    cl.sort(key=lambda x: (-x["rank"]["rank"], -x["f30"][0]))
    for k, x in enumerate(cl, 1): x["flag"] = ("close", f"Close #{k}", x["flag"][2] + f". Worst first, {k} of {len(cl)}.")
    ro = [x for x in ents if x.get("flag") and x["flag"][0] == "reopen"]
    if ro:
        ids = list(range(len(ro))); sc = _score({i: ro[i]["l"] for i in ids}); order = sorted(ids, key=lambda i: -sc[i])
        om = sorted(ids, key=lambda i: -ro[i]["l"][6]); oc = sorted(ids, key=lambda i: -(roas(ro[i]["l"]) or 0))
        for k, i in enumerate(order, 1):
            x = ro[i]; x["flag"] = ("reopen", f"Reopen #{k}", x["flag"][2] + f" Best first, {k} of {len(ro)}.")
            x["rr"] = dict(n=len(ro), k=k, mp=om.index(i) + 1, cp=oc.index(i) + 1)

rows = []
for n, days in by.items():
    st, L = meta[n]; L = dt.date.fromisoformat(L)
    r = dict(key=n, n=n.replace("Tracked | ", "").replace(" | Campaign", ""), act=st == "ACTIVE", L=L, live=(TODAY - L).days + 1)
    r["m2"] = metrics(days, r["act"]); rows.append(r)
rows = [r for r in rows if r["m2"]["l"][0] > 0]
FIRST = min(d for days in by.values() for d in days if days[d][0] > 0)
rows.sort(key=lambda r: (not r["act"], -r["m2"]["m"][0], -r["m2"]["l"][0]))
tot = {k: [sum(r["m2"][k][i] for r in rows) for i in range(10)] for k in ["t", "pt", "w", "pw", "x", "px", "m", "pm", "l"]}
_rk = rank_group({i: r["m2"] for i, r in enumerate(rows) if r["act"]})
_pk = period_ranks({i: r["m2"] for i, r in enumerate(rows) if r["act"]})
for i, r in enumerate(rows):
    m = r["m2"]; m["prk"] = _pk.get(i); m["rank"] = _rk.get(i); m["sig"] = sig_for(m); m["flag"] = flag_for(m); m["diag"] = diagnose(m) if r["act"] else None
finalize([r["m2"] for r in rows])
_go = [r["m2"] for r in rows if r["m2"].get("rr")]
if _go:
    sc = _score({i: x["l"] for i, x in enumerate(_go)})
    for k, i in enumerate(sorted(range(len(_go)), key=lambda i: -sc[i]), 1): _go[i]["rr"]["g"] = k; _go[i]["rr"]["gn"] = len(_go)

# ---- account level budget signal (profit-maximisation engine, same constants as the non-tracked report) ----
SCALE_MCR, HOLD_MCR, MIN_SPEND_CHANGE, MIN_ORDERS, HEADROOM_ACR = 1.20, 0.90, 0.10, 6, 1.50
day_tot = {}
for days in by.values():
    for d, v in days.items(): day_tot[d] = add(day_tot.get(d, [0.0] * 10), v)
def win(end, n):
    v = [0.0] * 10
    for i in range(n):
        v = add(v, day_tot.get((end - D(i)).isoformat(), [0.0] * 10))
    if (end - D(n - 1)).isoformat() < FIRST: return None
    c = v[6] * CONTRIB
    return dict(v=v, s=v[0], r=v[6], o=v[5], c=c, p=c - v[0], days=n, roas=roas(v), cpa=cpa(v), aov=aov(v), conv=convr(v))
def compare(cur, prev):
    if not cur or not prev or prev["s"] <= 0: return None
    dS = (cur["s"] - prev["s"]) / cur["days"] if cur["days"] == prev["days"] else cur["s"] / cur["days"] - prev["s"] / prev["days"]
    dC = cur["c"] / cur["days"] - prev["c"] / prev["days"]
    chg = (cur["s"] / cur["days"]) / (prev["s"] / prev["days"]) - 1
    res = dict(cur=cur, prev=prev, spend_chg=chg, mode=None, ratio=None, verdict=None, dS=dS, dC=dC)
    if abs(chg) < MIN_SPEND_CHANGE: res["mode"] = "flat"
    else:
        res["mode"] = "up" if dS > 0 else "down"; res["ratio"] = dC / dS
        res["verdict"] = "up" if res["ratio"] >= SCALE_MCR else ("down" if res["ratio"] < HOLD_MCR else "neutral")
    return res
def sig_account(end):
    cmp = {n: compare(win(end, n), win(end - D(n), n)) for n in (7, 14, 28)}
    cur = win(end, 14); Pm = cmp[14]; rec = cmp[7]; base = cmp[28]
    out = dict(code="hold", cur=cur, cmp=Pm, why="", details=[])
    if not cur or cur["s"] <= 0:
        out.update(code=None, why="No data for this period."); return out
    acr = cur["c"] / cur["s"]
    head = f"Each $1 of ads currently returns ${acr:.2f} of contribution (ROAS {roasf(cur['roas'])} vs break-even {roasf(BE_ROAS)})"
    r_v = rec["verdict"] if rec and rec["mode"] != "flat" else None
    b_v = base["verdict"] if base and base["mode"] != "flat" else None
    if cur["roas"] is not None and cur["roas"] < BE_ROAS and cur["p"] <= 0:
        code, why = "down", f"ROAS {roasf(cur['roas'])} is below break-even {roasf(BE_ROAS)} and the period is making a loss. Reduce budget and reassess."
    elif cur["o"] < MIN_ORDERS:
        code, why = "hold", f"Only {int(cur['o'])} tracked orders in this period, too few to justify a budget change. Maintain budget while more data accumulates."
    elif not Pm or Pm["mode"] == "flat":
        if acr >= HEADROOM_ACR and cur["p"] > 0: code, why = "up", f"Spend has been steady, so the extra-spend test can't be read yet. {head}, so there is clear room to scale. Raise budget about 20% and re-check after 14 days."
        else: code, why = "hold", f"Spend has been steady, so the extra-spend test can't be read yet. {head}; not enough headroom to scale confidently."
    elif Pm["mode"] == "up":
        mcr = Pm["ratio"]
        if mcr >= SCALE_MCR and cur["p"] > 0:
            if r_v == "down" and b_v == "down" and acr < HEADROOM_ACR: code, why = "hold", "Extra spend paid off over the last 14 days, but both the last 7 days and the 28-day baseline point the other way. Maintain budget until the trend is consistent."
            else: code, why = "up", "Additional spend is still increasing total profit. Marginal contribution remains positive."
        elif mcr < HOLD_MCR:
            if r_v == "up": code, why = "hold", "Extra spend returned less than it cost, but the last 7 days show a strong recovery. Maintain budget rather than cutting on short-term noise."
            else: code, why = "down", "Recent additional spend is producing less contribution than it costs. Reduce budget and reassess."
        else: code, why = "hold", "Current spend is profitable, but marginal profit is flattening. Maintain budget while more data accumulates."
    else:
        if Pm["verdict"] == "up" and cur["p"] > 0 and not (r_v == "down" and acr < HEADROOM_ACR):
            code, why = "up", f"Spend fell and profit fell with it: each $1 saved cost ${Pm['ratio']:.2f} of contribution. The account looks under-scaled; restoring spend should increase total profit."
        else: code, why = "hold", "Spend fell and profit moved roughly in line, or the trend is mixed. Maintain budget while more data accumulates."
    det = [f"Last 14 full days vs the 14 before (per-day basis)."]
    for nm, w in (("14-day", Pm), ("7-day", rec), ("28-day", base)):
        if not w: det.append(f"{nm}: not available."); continue
        sc = f"{w['spend_chg']*100:+.0f}%"
        if w["mode"] == "flat": det.append(f"{nm}: spend {sc}, under 10% change, so marginal return isn't measured.")
        elif w["mode"] == "up": det.append(f"{nm}: spend {sc}; each extra $1 of ads produced ${w['ratio']:.2f} of contribution.")
        else: det.append(f"{nm}: spend {sc}; each $1 saved lost ${w['ratio']:.2f} of contribution.")
    det.append(f"Average contribution return: ${acr:.2f} per $1 of ads (Scale Up needs ${HEADROOM_ACR:.2f}+ when the extra-spend test can't be read).")
    det.append(f"Guardrail: ROAS {roasf(cur['roas'])} vs break-even {roasf(BE_ROAS)}; period net profit {money0(cur['p'])}. Contribution = sales x {CONTRIB:.2f} (after GST and product cost).")
    out.update(code=code, why=why, details=det); return out
RS = sig_account(FULL_END); c14 = RS["cur"]
SIGCLS = {"up": "scale", "hold": "hold", "down": "cut"}.get(RS["code"], "hold")
SIGLBL = {"up": "Scale Up", "hold": "Hold Budget", "down": "Scale Down"}.get(RS["code"], "No signal")
if RS["cmp"] and RS["cmp"]["mode"] == "up": MRV = f'{RS["cmp"]["ratio"]:.2f}'; MRL = "marginal return (each extra $1)"
elif RS["cmp"] and RS["cmp"]["mode"] == "down": MRV = "Spend fell"; MRL = "marginal return: see why"
else: MRV = f'${c14["c"]/c14["s"]:.2f}' if c14 and c14["s"] else "—"; MRL = "return per $1 of ads now (spend too steady for the extra-spend test)"

# ---- rendering helpers ----
def rkcol(pos, n):
    if not pos or n <= 1: return "n"
    if n == 2: return "g" if pos == 1 else "y"
    f = (pos - 1) / (n - 1)
    return "g" if f <= 1/3 else ("r" if f >= 2/3 else "y")
def rkbadge(rk, key):
    if not rk or not rk.get("r" + key): return ""
    pos, n = rk["r" + key], rk["n" + key]
    c = "g1" if (pos == 1 and n > 1) else "g2" if (pos == 2 and n > 2) else "g3" if (pos == 3 and n > 3) else {"g": "cg", "y": "cy", "r": "cr", "n": "cn"}[rkcol(pos, n)]
    return f'<span class="mdl {c}" title="Rank #{pos} of {n} in this period, by tracked sales (70%) and ROAS (30%). 1 is best."><span class="mg"><i>{pos}</i></span></span>'
KEYMAP = {"Today": "t", "Week": "w", "15d": "x", "Month": "m", "Lifetime": "l"}
def trio(cur, prev, lab, rk=None):
    k = KEYMAP[lab]
    if not cur[0]: return f'<td class="s1 c{k}" data-l="{lab} spend">—</td><td class="c{k}" data-l="{lab} sales">—</td><td class="c{k}" data-l="{lab} ROAS">—</td>'
    pv = prev if prev and prev[0] else None
    r = roas(cur); pr = roas(pv) if pv else None
    return (f'<td class="s1 c{k}" data-l="{lab} spend">{rkbadge(rk, {"t":"1","w":"7","x":"15","m":"30"}.get(k, "")) if rk else ""}{money(cur[0])}{arrow(cur[0], pv[0], None) if pv else ""}</td>'
            f'<td class="c{k}" data-l="{lab} sales">{money(cur[6]) if cur[6] else "$0"}{arrow(cur[6], pv[6], True) if pv else ""}<small class="inl">{int(cur[5])} order{"s" if int(cur[5]) != 1 else ""}</small></td>'
            f'<td class="c{k}" data-l="{lab} ROAS"><span class="p {band(r)}">{roasf(r)}</span>{arrow(r, pr, True) if (pr is not None and r is not None) else ""}</td>')
def hrag(p, n): return "n" if n < 1 else ("g" if p >= 0.60 else ("y" if p >= 0.35 else "r"))
def hchip(b_, n_):
    if n_ <= 0: return '<span class="hv n" title="No days with spend in this window">–</span>'
    return f'<span class="hv {hrag(b_/n_, n_)}" title="{b_} of {n_} spend day{"s" if n_ > 1 else ""} at {TARGET_ROAS:.1f}x ROAS or better">{round(100*b_/n_)}%</span>'
def agenote(m):
    f, rs = m.get("first"), m.get("rs")
    if not f: return ""
    def ago(d): n = (TODAY - d).days; return "today" if n <= 0 else ("1 day ago" if n == 1 else f"{n} days ago")
    if (TODAY - f).days < 7: return f'<span class="hage">Launched {ago(f)}</span>'
    if rs > f and (TODAY - rs).days < 7: return f'<span class="hage">Reactivated {ago(rs)}</span>'
    return ""
def hcell(m):
    pre = agenote(m)
    if m["health"] == ("none", "Paused"):
        ch = "".join(f'<span class="hch"><span class="hcap">{cap}</span>{hchip(b_, n_)}</span>' for cap, (b_, n_) in (("7 days", m["h7"]), ("15 days", m["h15"]), ("30 days", (m["hb"], m["hn"])), ("Last run", m["lr"]), ("Lifetime", m["lh"])))
        last = f'<span class="hlast">Paused. Last spend {m["ls"].strftime("%-d %b")}</span>' if m["ls"] else '<span class="hlast">Paused, no spend</span>'
        return f'<td class="s1 hc">{pre}<span class="hcs">{ch}</span>{last}</td>'
    chips = "".join(f'<span class="hch"><span class="hcap">{cap}</span>{hchip(b_, n_)}</span>' for cap, (b_, n_) in (("7 days", m["h7"]), ("15 days", m["h15"]), ("30 days", (m["hb"], m["hn"])), ("Current run", m["lr"]), ("Lifetime", m["lh"])))
    return f'<td class="s1 hc">{pre}<span class="hcs">{chips}</span></td>'
def rkrow_p(m):
    r = m.get("rr")
    if not r: return ""
    ch = "".join(f'<span class="rkc {rkcol(pos, r["n"])}" title="Rank among paused candidates on lifetime {t}, out of {r["n"]}">{cap} #{pos}</span>' for cap, pos, t in (("Sales", r["mp"], "tracked sales"), ("ROAS", r["cp"], "ROAS")))
    return f'<span class="rkrow"><span class="rkl">Reopen rank <b>#{r["k"]}</b> of {r["n"]}{f" · all paused #{r[chr(103)]} of {r[chr(103)+chr(110)]}" if r.get("g") else ""}</span>{ch}</span>'
def sigrow(sg, fl=None):
    x = fl or sg
    return f'<span class="sigrow"><span class="sp {x[0]}" title="{html.escape(x[2])}">{x[1]}</span><small>{html.escape(x[2])}</small></span>' if x else ""
def prow(cls, name, m, attrs=""):
    return (f'<tr class="{cls}"{attrs}>{name}' + hcell(m)
            + trio(m["t"], m["pt"], "Today", m.get("prk")) + trio(m["w"], m["pw"], "Week", m.get("prk")) + trio(m["x"], m["px"], "15d", m.get("prk")) + trio(m["m"], m["pm"], "Month", m.get("prk")) + trio(m["l"], None, "Lifetime") + '</tr>')

# colour ratings for funnel metrics: g = green (good), b = blue (okay), r = red (needs fixing). None = volume, no colour.
def _tier(x, g, b, higher=True):
    if x is None: return None
    if higher: return "g" if x >= g else ("b" if x >= b else "r")
    return "g" if x <= g else ("b" if x <= b else "r")
RT = dict(
    ctr=lambda v: _tier(lctr(v), 0.015, 0.010),
    cpc=lambda v: _tier(lcpc(v), 0.70, 1.00, False),
    cpm=lambda v: _tier(cpm_(v), 15, 25, False),
    lpv=lambda v: _tier(lpvr(v), 0.80, 0.70),
    atc=lambda v: _tier(atcr(v), 0.10, 0.05),
    chk=lambda v: _tier(icr(v), 0.30, 0.20),
    ordr=lambda v: _tier(pcr(v), 0.25, 0.15),
    conv=lambda v: _tier(convr(v), 0.02, 0.01),
    cpa=lambda v: ({"g": "g", "b": "b", "r": "r", "none": None}[band(roas(v))] if v[0] and v[5] else ("r" if v[0] >= 40 else None)),
    profit=lambda v: ("g" if profit(v) > 0 else "r") if v[0] else None,
)
def pill(txt, cls): return f'<span class="p {cls}">{txt}</span>' if cls else txt

# funnel detail rows (shown when a campaign is expanded): same three-cells-per-period grid as the main row
def drow(label, m, fns, diag_html=""):
    cells = ""
    for lab in ("Today", "Week", "15d", "Month", "Lifetime"):
        k = KEYMAP[lab]; v = m[k]; pv = m.get("p" + k)
        for j, (cap, fn, hg, rt) in enumerate(fns):
            a = fn(v); b = fn(pv) if (pv and pv[0]) else None
            txt = pill(a[0], rt(v) if rt else None) if a is not None else "—"
            cells += f'<td class="{"s1 " if j == 0 else ""}c{k}" data-l="{lab} {cap}">{txt if v[0] else "—"}{arrow(a[1], b[1], hg) if (a is not None and b is not None and v[0] and hg is not None) else ""}</td>'
    return (f'<th scope="row" class="asn"><div class="asw"><div class="asb"><span class="nm">{label}</span></div></div></th><td class="s1 hc">{diag_html}</td>' + cells)
def F(f, fmt): return lambda v: (lambda x: None if x is None else (fmt(x), x))(f(v))
FN1 = [("link clicks", F(lambda v: v[3], num), True, None), ("link CTR", F(lctr, lambda x: pct(x, 2)), True, RT["ctr"]), ("CPC", F(lcpc, lambda x: f"${x:.2f}"), False, RT["cpc"])]
FN2 = [("add to cart", F(lambda v: v[7], num), True, RT["atc"]), ("click to order", F(convr, lambda x: pct(x, 1)), True, RT["conv"]), ("cost/order", F(cpa, lambda x: f"${x:.2f}"), False, RT["cpa"])]
FN3 = [("orders", F(lambda v: v[5], num), True, RT["ordr"]), ("avg order", F(aov, lambda x: f"${x:,.0f}"), True, None), ("net profit", F(lambda v: profit(v), money0), True, RT["profit"])]
def diag_html(m):
    d = m.get("diag")
    if not m["act"]: return '<span class="hlast">Paused: no diagnosis</span>'
    if d is None: return '<span class="hlast">Too little traffic in the last 30 days to diagnose</span>'
    lab, iss = d
    if iss is None: return f'<span class="hlast">Too little traffic in the last {lab} to diagnose (needs 40+ link clicks and $20 spend)</span>'
    if not iss: return f'<span class="dgl"><span class="dgt ok">Healthy</span> No funnel step is under benchmark (last {lab}).</span>'
    return "".join(f'<span class="dgl"><span class="dgt {"bad" if sv < 0.6 else "mid"}">{html.escape(tag)}</span> {html.escape(tx)}</span>' for sv, tag, tx in iss) + f'<span class="hlast">Last {lab}</span>'

trs = ""; first_p = True
for i, r in enumerate(rows):
    cls = "cp act" if r["act"] else "cp paused"
    if not r["act"] and first_p: cls += " firstp"; first_p = False
    m = r["m2"]
    btn = '<button type="button" class="xp" aria-expanded="false" aria-label="Show funnel details">&#9656;</button>'
    nm = (f'<th scope="row" title="Launched {r["L"].strftime("%-d %b %Y")} ({r["live"]} days ago)"><div class="nmrow">{btn}<span class="nmw"><span class="nm">{html.escape(r["n"])}</span>'
          f'<span class="meta"><span class="st {"on" if r["act"] else "off"}">{"Active" if r["act"] else "Paused"}</span><span class="ln2">funnel details</span></span>'
          + (sigrow(m.get("sig"), m.get("flag")) if r["act"] else sigrow(None, m.get("flag")) + rkrow_p(m)) + '</span></div></th>')
    trs += '<tbody class="grp">' + prow(cls, nm, m, f' data-id="c{i}"')
    trs += f'<tr class="as" data-p="c{i}" hidden>{drow("Traffic: link clicks, CTR, cost per click", m, FN1, diag_html(m))}</tr>'
    trs += f'<tr class="as" data-p="c{i}" hidden>{drow("Buying: carts, click to order, cost per order", m, FN2)}<!-- --></tr>'.replace("<!-- -->", "")
    trs += f'<tr class="as" data-p="c{i}" hidden>{drow("Result: orders, average order, net profit", m, FN3)}</tr>'
    trs += '</tbody>'
trs += ('<tbody><tr class="total"><th scope="row">All tracked campaigns</th><td class="s1"></td>' + trio(tot["t"], tot["pt"], "Today") + trio(tot["w"], tot["pw"], "Week") + trio(tot["x"], tot["px"], "15d")
        + trio(tot["m"], tot["pm"], "Month") + trio(tot["l"], None, "Lifetime") + '</tr></tbody>')
# the "as" rows of the detail section need a blank cell where the health column sits for rows 2 and 3
trs = trs.replace('</div></div></th><td class="s1 hc"></td>', '</div></div></th><td class="s1 hc"></td>')

def kpi(k, label, rg, cur, prev, note, extra=""):
    pv = prev if prev and prev[0] else None
    r = roas(cur); pr = roas(pv) if pv else None
    def b(val, fmt, pval=None, hg=None): return f'{fmt(val)}{arrow(val, pval, hg) if pval is not None else ""}'
    def cell(val, cap, pval=None, hg=None, fmt=money, rt=None):
        txt = fmt(val); cls = rt(cur) if rt else None
        return f'<div><b>{pill(txt, cls)}{arrow(val, pval, hg) if pval is not None else ""}</b><span>{cap}</span></div>'
    c1 = cell(cur[0], "spent", pv[0] if pv else None, None) + cell(cur[6], "tracked sales", pv[6] if pv else None, True, lambda x: money(x) if x else "$0") + f'<div><b class="ro"><span class="p {band(r)}">{roasf(r)}</span>{arrow(r, pr, True) if (pr is not None and r is not None) else ""}</b><span>ROAS</span></div>'
    c2 = (cell(cur[5], "orders", pv[5] if pv else None, True, num) + cell(cpa(cur), "cost per order", cpa(pv) if pv else None, False, lambda x: f"${x:,.2f}" if x else "—", RT["cpa"]) + cell(profit(cur), "net profit", profit(pv) if pv else None, True, money0, RT["profit"]))
    c3 = (cell(cur[3], "link clicks", pv[3] if pv else None, True, num) + cell(lctr(cur), "link CTR", lctr(pv) if pv else None, True, lambda x: pct(x, 2) if x is not None else "—", RT["ctr"]) + cell(lcpc(cur), "cost per click", lcpc(pv) if pv else None, False, lambda x: f"${x:.2f}" if x is not None else "—", RT["cpc"]))
    return (f'<div class="kpi k{k}"><h2>{label}</h2><p class="rg">{rg}</p><div class="kv">{c1}</div>'
            f'<div class="kv sv">{c2}</div><div class="kv sv">{c3}</div><p class="kn">{note}</p>{extra}</div>')

cp_ = c14
SIGP = f'''<section class="sig {SIGCLS}"><div class="sg"><span class="sgl">Budget signal</span><b>{SIGLBL}</b><p>{html.escape(RS["why"])}</p></div>
<div class="sgm"><div><b>{roasf(cp_["roas"]) if cp_ else "—"}</b><span>ROAS</span></div><div><b>{roasf(BE_ROAS)}</b><span>break-even ROAS</span></div><div><b>{money(cp_["cpa"]) if cp_ and cp_["cpa"] else "—"}</b><span>cost per order</span></div><div><b>{money(cp_["aov"]) if cp_ and cp_["aov"] else "—"}</b><span>average order</span></div><div><b>{pct(cp_["conv"]) if cp_ else "—"}</b><span>link click to order</span></div><div><b>{MRV}</b><span>{MRL}</span></div></div>
<p class="sgn">Last 14 full days, {(FULL_END - D(13)).strftime("%-d %b")} to {FULL_END.strftime("%-d %b")}: {money(cp_["s"])} spend, {int(cp_["o"])} tracked orders, {money(cp_["r"])} sales, {money0(cp_["p"])} net profit. Break-even ROAS = 1 / 0.68 (what's left of each sales dollar after GST and product cost); a safety guardrail, not the decision.</p>
<details class="sgn why"><summary>Why this signal</summary><ul>{"".join(f"<li>{html.escape(x)}</li>" for x in RS["details"])}</ul></details></section>''' if cp_ else ""

def fcol(k, label):
    v = tot[k]; pv = tot.get("p" + k) if k != "l" else None
    return v, pv
GLOSS = [
 ("Spend", "Money Meta charged for the ads in the period.", "Your cost of buying attention. On its own it is neither good nor bad; read it against sales.", "Grey arrow: up or down vs the previous period (not good or bad)."),
 ("Tracked sales", "Purchase value Meta recorded from the pixel and conversions API for these campaigns, including GST.", "Real orders that Meta can tie to an ad click, not messages or leads. Meta can miss some buyers, so true sales are usually a little higher.", "Green arrow up, red arrow down."),
 ("ROAS", "Tracked sales divided by spend. 5.00x means $5 of sales for every $1 of ads.", "The main success measure. It says whether the ads pay for themselves before other costs.", f"Green {TARGET_ROAS:.1f}x or more. Blue {BE_ROAS:.2f}x to {TARGET_ROAS:.1f}x (covers costs, thin profit). Red under {BE_ROAS:.2f}x (losing money)."),
 ("Break-even ROAS", f"1 / 0.68 = {BE_ROAS:.2f}x. Each sales dollar leaves 68 cents after GST (1/11) and product cost (25% of ex-GST sales).", "The ROAS where an order stops losing money on ads alone. Fixed costs (staff, platform, management) still sit on top.", "The red / blue line for ROAS."),
 ("Orders", "Number of purchase events Meta recorded.", "Volume of real buyers. Few orders make every ratio noisy, so judge ROAS on 7 to 30 days, not one day.", "Coloured by orders as a share of checkouts: green 25%+, blue 15% to 25%, red under 15%."),
 ("Cost per order", "Spend divided by orders.", "What it costs to win one customer. Compare it with average order value: it is only good if orders are worth much more than this.", "Follows ROAS: green at 2.0x+, blue at 1.47x to 2.0x, red below. Red also if $40+ was spent with no orders."),
 ("Net profit", "Tracked sales x 0.68 minus spend.", "Money left after GST, product cost and ad spend, before fixed costs.", "Green above $0, red below $0."),
 ("Impressions", "Times the ads appeared on screen.", "Reach of the campaign. Enough impressions are needed for results to be reliable.", "No colour: volume only."),
 ("Link clicks", "Clicks on the ad that lead to the website (not likes, comments or profile clicks).", "Real visits bought. This is the traffic the rest of the funnel works on.", "No colour: volume only."),
 ("Link CTR", "Link clicks divided by impressions.", "Whether the ad (image, hook, offer) makes people want to click. Low CTR points at the creative.", "Green 1.5%+, blue 1% to 1.5%, red under 1%."),
 ("Cost per click", "Spend divided by link clicks.", "Price of a visit. High with decent CTR means an expensive or crowded audience; high with low CTR means weak creative.", "Green under $0.70, blue $0.70 to $1.00, red over $1.00."),
 ("CPM", "Spend per 1,000 impressions.", "Price of attention. Rising CPM means more competition or a narrow or tired audience, before anyone clicks.", "Green under $15, blue $15 to $25, red over $25."),
 ("Landing page views", "Link clicks where the site actually finished loading.", "Landing page views divided by link clicks shows click quality and site speed. A big gap means slow pages or accidental clicks.", "Coloured by views as a share of link clicks: green 80%+, blue 70% to 80%, red under 70%."),
 ("Add to cart", "Times a product was added to the cart.", "Buying intent. Carts divided by landing page views tells you if the right people, product and price are arriving.", "Coloured by carts as a share of landing page views: green 10%+, blue 5% to 10%, red under 5%. Low points at targeting or offer."),
 ("Checkouts started", "Times a checkout was begun.", "Carts that became serious intent. A big drop from carts means price shock or shipping cost.", "Coloured by checkouts as a share of carts: green 30%+, blue 20% to 30%, red under 20%."),
 ("Click to order", "Orders divided by link clicks.", "The overall conversion rate of paid traffic. It combines ad quality, site and checkout in one number.", "Green 2%+, blue 1% to 2%, red under 1%."),
 ("Average order", "Tracked sales divided by orders.", "How much each customer spends. Low average order makes ROAS hard even when conversion is fine; fix with bundles or higher-value items.", "No colour."),
 ("Health", f"Share of days with spend where ROAS was {TARGET_ROAS:.1f}x or better, for the last 7, 15 and 30 full days, the current run and lifetime.", "Consistency. A campaign can have one big day; health shows whether it keeps winning.", "Green 60%+, amber 35% to 59%, red under 35%. Red also if 30 days of spend produced no orders."),
 ("Rank", "Score of 70% tracked sales plus 30% ROAS among active campaigns. Overall rank blends 30 days (60%) and 7 days (40%).", "Which campaigns deserve budget first. 1 is best. Under $20 spend in the window is not ranked.", "Medals 1 to 3 gold, silver, bronze. Then green top third, red bottom third."),
 ("Flags and spend signal", "Close, Reopen, Keep closed, Spend more, Spend less, Hold, from health, rank and 7-day versus 30-day ROAS.", "A suggested action for the marketer, not an automatic change.", "Hover or read the line under the flag for the reason."),
 ("Budget signal (account)", "Compares the last 14 full days with the 14 before: did the extra spend return more than $1.20 of contribution per extra $1?", "Whether to raise, hold or cut total budget based on profit, not just ROAS.", "Green Scale Up, amber Hold Budget, red Scale Down."),
 ("Marginal return", "Extra contribution divided by extra spend between two periods.", "The return on the last dollars spent. It is usually lower than average ROAS and tells you whether scaling still pays.", "Above 1.20 supports scaling, below 0.90 supports cutting."),
]
GD = {n: (d, w, c) for n, d, w, c in GLOSS}
_rb = lambda v: ({"g": "g", "b": "b", "r": "r"}.get(band(roas(v))))
FROWS = [("Spend", lambda v: money(v[0]), None), ("Tracked sales", lambda v: money(v[6]) if v[6] else "$0", None), ("ROAS", lambda v: roasf(roas(v)), _rb),
         ("Impressions", lambda v: num(v[1]), None), ("Link clicks", lambda v: num(v[3]), None), ("Link CTR", lambda v: pct(lctr(v), 2), RT["ctr"]), ("Cost per click", lambda v: f"${lcpc(v):.2f}" if lcpc(v) is not None else "—", RT["cpc"]),
         ("CPM", lambda v: f"${cpm_(v):.2f}" if cpm_(v) is not None else "—", RT["cpm"]), ("Landing page views", lambda v: num(v[9]), RT["lpv"]), ("Add to cart", lambda v: num(v[7]), RT["atc"]),
         ("Checkouts started", lambda v: num(v[8]), RT["chk"]), ("Orders", lambda v: num(v[5]), RT["ordr"]), ("Click to order", lambda v: pct(convr(v), 1), RT["conv"]), ("Cost per order", lambda v: f"${cpa(v):,.2f}" if cpa(v) is not None else "—", RT["cpa"]),
         ("Average order", lambda v: f"${aov(v):,.0f}" if aov(v) is not None else "—", None), ("Net profit", lambda v: money0(profit(v)), RT["profit"])]
NUMS = {"Spend": (lambda v: v[0], None), "Tracked sales": (lambda v: v[6], True), "ROAS": (roas, True), "Impressions": (lambda v: v[1], None), "Link clicks": (lambda v: v[3], True),
        "Link CTR": (lctr, True), "Cost per click": (lcpc, False), "CPM": (cpm_, False), "Landing page views": (lambda v: v[9], True), "Add to cart": (lambda v: v[7], True),
        "Checkouts started": (lambda v: v[8], True), "Orders": (lambda v: v[5], True), "Click to order": (convr, True), "Cost per order": (cpa, False), "Average order": (aov, True), "Net profit": (profit, True)}
def _frow(lab, fn, rt):
    d, w, c = GD[lab]; nf, hg = NUMS[lab]; cells = ""
    for k in "twml":
        v = tot[k]; pv = tot.get("p" + k) if k != "l" else None
        ar = arrow(nf(v), nf(pv), hg) if (pv and pv[0] and v[0]) else ""
        cells += f'<td class="c{k}" data-l="{ {"t":LBL_T,"w":"7 days","m":"30 days","l":"Lifetime"}[k] }">{pill(fn(v), rt(v) if rt else None) if v[0] else "—"}{ar}</td>'
    return (f'<tr class="kr"><th scope="row"><button type="button" class="kb" aria-expanded="false" aria-label="Show definition">&#9656;</button>{lab}</th>{cells}</tr>'
            f'<tr class="kdef" hidden><td colspan="5"><dl><dt>Definition</dt><dd>{html.escape(d)}</dd><dt>What it tells you</dt><dd>{html.escape(w)}</dd><dt>Colour</dt><dd>{html.escape(c)}</dd></dl></td></tr>')
frows = "".join(_frow(*r) for r in FROWS)
fix = ""
for r in rows:
    if not r["act"]: continue
    fix += f'<h3>{html.escape(r["n"])}</h3>' + diag_html(r["m2"])
SECTION = SIGP + f'''<section class="two">
<div class="box"><h2>Funnel across all tracked campaigns</h2><p class="sub">Click any row for its definition, what it tells you and how it is coloured. Arrows compare with the previous period: green is better, red is worse, grey is spend or volume. Sales are Meta purchase value (includes GST). Net profit = sales x 0.68 minus ad spend.</p>
<div class="tw"><table class="mini"><thead><tr><th></th><th class="ct">{LBL_T}</th><th class="cw">7 days</th><th class="cm">30 days</th><th class="cl">Lifetime</th></tr></thead><tbody>{frows}</tbody></table></div></div>
<div class="box att"><h2>What to fix</h2><p class="sub">Biggest funnel leaks for each active campaign against fixed benchmarks.</p>{fix}</div>
</section>'''


# ---- reuse the non-tracked report's CSS and scripts so the look and feel is identical ----
_src = open(os.path.join(HERE, "build.py"), encoding="utf-8").read()
_a = _src.index("<style>\n") + 8; _b = _src.index("</style>", _a)
_dk = re.search(r'^DK="(.*)"$', _src, re.M).group(1)
def _undo(t): return t.replace("{{", "\x00").replace("}}", "\x01").replace("\x00", "{").replace("\x01", "}")
CSS = _undo(_src[_a:_b]).replace("{DK}", _dk)
CSS += """
.kb{background:none;border:0;cursor:pointer;color:var(--muted);font-size:12px;padding:0 6px 0 0}
tr.kdef td{background:var(--sub);padding:8px 12px;text-align:left;font-size:13px;white-space:normal}
tr.kdef dl{margin:0;display:grid;grid-template-columns:130px 1fr;gap:4px 12px}tr.kdef dt{font-weight:600;color:var(--muted)}tr.kdef dd{margin:0}
tr.kr th{cursor:pointer}
.p.b{background:var(--tb);color:var(--t);border-color:color-mix(in srgb,var(--t) 40%,transparent)}
.inl{display:block;font-size:11px;font-weight:400;color:var(--muted);line-height:1.2}
.dgl{display:block;margin:3px 0;font-size:12.5px;line-height:1.35}
.dgt{display:inline-block;font-size:11px;font-weight:700;padding:0 6px;border-radius:5px;margin-right:4px;background:var(--sub);color:var(--ink)}
.dgt.bad{background:var(--rb);color:var(--r)}.dgt.mid{background:var(--yb);color:var(--y)}.dgt.ok{background:var(--gb);color:var(--g)}
tr.as th.asn .nm{font-weight:600;font-size:12.5px}
.att h3{margin:12px 0 4px}
"""
_c = _src.index("</main>", _b)
_s1 = _src.index("<script>", _c); _s2 = _src.index("</script>{PRODS_TAG}", _s1) + len("</script>")
JS = _undo(_src[_s1:_s2]) + "<script>document.querySelectorAll('tr.kr').forEach(function(r){r.addEventListener('click',function(){var d=r.nextElementSibling,o=d.hidden;d.hidden=!o;var b=r.querySelector('.kb');b.setAttribute('aria-expanded',o);b.innerHTML=o?'&#9662;':'&#9656;'})})</script>"

legend = (f'<p class="key"><button class="tg" id="xa" type="button" data-o="0">Expand all funnel details</button><span class="p g">ROAS {TARGET_ROAS:.1f}x or more</span><span class="p b">{BE_ROAS:.2f}x to {TARGET_ROAS:.1f}x</span><span class="p r">Under {BE_ROAS:.2f}x (losing money)</span><span>Funnel numbers: green good, blue okay, red needs fixing</span>'
          '<span>▲▼ change vs the previous period: green is better, red is worse, grey is spend</span></p>')
HOW = f'''<details class="how"><summary>How to read health, rank, flags and the funnel</summary><dl>
<dt>ROAS and net profit</dt><dd>ROAS is tracked sales divided by spend. Tracked sales are the purchase value Meta recorded from the Meta pixel and conversions API for these campaigns (includes GST). Each sales dollar leaves 68 cents after GST and product cost, so break-even ROAS is {BE_ROAS:.2f}x and net profit is sales x 0.68 minus spend. Green is {TARGET_ROAS:.1f}x or more, blue between break-even and {TARGET_ROAS:.1f}x, red under break-even. Funnel numbers use the same three colours against the benchmarks listed under Funnel details.</dd>
<dt>Health</dt><dd>Share of days with spend where ROAS was {TARGET_ROAS:.1f}x or better, for the last 7, 15 and 30 full days. Green is 60% or more, amber 35 to 59%, red under 35%; red also if there was spend in 30 days with no orders at all. Every window is colour coded from the first spend day; a dash means no spend in that window. Campaigns under 7 days old show <b>Launched N days ago</b>, or <b>Reactivated N days ago</b> after a gap of over 3 days.</dd>
<dt>Rank</dt><dd>The small medal next to each spend figure is the rank for that period alone (yesterday, 7, 15, 30 days); 1 is best, among the active campaigns that spent in it. Score is 70% tracked sales plus 30% ROAS; the overall rank blends 30 days (60%) and 7 days (40%) of full days. Green is the top third, red the bottom third; under $20 spend in a window is not ranked.</dd>
<dt>Flags</dt><dd><b>Close #1</b> (active): 30-day health is red or amber, 7-day health is not green, at least $20 spent in 30 days, and it ranks in the bottom half. #1 is the worst. <b>Reopen #1</b> (paused): lifetime health is green over at least 5 spend days and $50 spent. <b>Keep closed</b> (paused): lifetime health is red on the same evidence. Paused rows show 7, 15 and 30 day health plus Last run and Lifetime.</dd>
<dt>Spend signal</dt><dd>Spend more when 30-day health is Good and the 7-day ROAS is at or above both the 30-day ROAS and {TARGET_ROAS:.1f}x. Spend less when health is Poor or the 7-day ROAS is under break-even. Otherwise Hold. The account-level Budget signal at the top uses the same profit engine as the non-tracked report: it asks whether the last 14 days of extra spend returned more than $1.20 of contribution per extra $1.</dd>
<dt>Funnel details</dt><dd>Click a campaign to open three rows under it, in the same Today / 7 / 15 / 30 day / Lifetime columns: <b>Traffic</b> (link clicks, link CTR, cost per click), <b>Buying</b> (add to cart, link click to order rate, cost per order) and <b>Result</b> (orders, average order, net profit). The health column of the Traffic row names the biggest leaks, tagged Creative, Audience, Landing page, Targeting / offer, Cart or Checkout. Benchmarks: link CTR 1%+, cost per click under $1, 70%+ of clicks load the page, 10%+ of visitors add to cart, 30%+ of carts reach checkout, 25%+ of checkouts become orders. Needs 40+ link clicks and $20 spend.</dd>
<dt>Notes</dt><dd>Only campaigns with "Tracked" in the name are included, never "Non Tracked". Periods end on {TODAY.strftime("%-d %b")}; arrows compare each period with the one before it. Health, rank and signal use completed days only.</dd></dl></details>'''

page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Tracked campaigns daily report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Figtree:wght@400;500;600&display=swap" rel="stylesheet">
<style>
{CSS}</style></head><body><main>
<header><div class="hd"><h1>Tracked campaigns, daily</h1><p>Webirox ad account, Meta sales campaigns with purchase tracking. Report for {TODAY.strftime("%A %-d %B %Y")}, updated {NOW.strftime("%-I:%M %p")} Sydney time.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>
<section class="kpis">
{kpi("t", LBL_T, TODAY.strftime("%a %-d %b %Y"), tot["t"], tot["pt"], "Arrows compare with the day before, " + YEST.strftime("%a %-d %b") + ("." if TODAY < REAL else ". Today is still in progress."))}
{kpi("w", "Last 7 days", W7.strftime("%-d %b") + " to " + TODAY.strftime("%-d %b %Y"), tot["w"], tot["pw"], "Arrows compare with the 7 days before, " + (W7 - D(7)).strftime("%-d %b") + " to " + (W7 - D(1)).strftime("%-d %b") + ".")}
{kpi("m", "Last 30 days", M30.strftime("%-d %b") + " to " + TODAY.strftime("%-d %b %Y"), tot["m"], tot["pm"], "Arrows compare with the 30 days before, " + (M30 - D(30)).strftime("%-d %b") + " to " + (M30 - D(1)).strftime("%-d %b") + ".")}
{kpi("l", "Lifetime", dt.date.fromisoformat(FIRST).strftime("%-d %b %Y") + " to " + TODAY.strftime("%-d %b %Y"), tot["l"], None, f"All {len(rows)} tracked campaigns, active and paused, from the first day of spend.")}
</section>
{SECTION}
{HOW}
{legend}
<div class="wrapx"><div class="wrap"><nav class="jump" aria-label="Jump to a period"><button type="button" class="stp" data-step="-1" aria-label="Previous">&#8249;</button><button type="button" data-i="0">Health</button><button type="button" data-i="1">{LBL_T}</button><button type="button" data-i="2">7 days</button><button type="button" data-i="3">15 days</button><button type="button" data-i="4">30 days</button><button type="button" data-i="5">Lifetime</button><button type="button" class="stp" data-step="1" aria-label="Next">&#8250;</button><button type="button" class="fsb" id="fsb" aria-label="Full screen">&#x26F6; Full screen</button></nav><table>
<thead><tr><th rowspan="2" class="hcamp">Campaign</th><th rowspan="2" class="s1 hh">Health<small>% of days at {TARGET_ROAS:.1f}x ROAS or better. Run = latest stretch of spend, no gap over 3 days</small></th><th colspan="3" class="s1 gh ct">{LBL_T}<small>{TODAY.strftime("%a %-d %b")}</small></th><th colspan="3" class="s1 gh cw">Last 7 days<small>{W7.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cx">Last 15 days<small>{M15.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cm">Last 30 days<small>{M30.strftime("%-d %b")} to {TODAY.strftime("%-d %b")}</small></th><th colspan="3" class="s1 gh cl">Lifetime<small>Since {dt.date.fromisoformat(FIRST).strftime("%-d %b %Y")}</small></th></tr>
<tr>{"".join(f'<th class="s1 c{k}">Spend</th><th class="c{k}">Sales</th><th class="c{k}">ROAS</th>' for k in "twxml")}</tr></thead>
{trs}</table></div></div>
</main>
{JS}</body></html>'''
sys.path.insert(0, HERE)
import tile_periods as _tp
_sp, _rv = {}, {}
for _c, _days in by.items():
    for _d, _v in _days.items(): _sp[_d] = _sp.get(_d, 0) + _v[0]; _rv[_d] = _rv.get(_d, 0) + _v[6]
page = page.replace("</body>", _tp.tag(_tp.periods(TODAY, _sp, _rv)) + "</body>", 1)
open(OUT, "w", encoding="utf-8").write(page)
for k in ("t", "w", "m", "l"):
    v = tot[k]; print(k, "spend", round(v[0], 2), "sales", round(v[6], 2), "orders", int(v[5]), "roas", roasf(roas(v)))
print("signal:", SIGLBL, "|", RS["why"][:160])

# ---- tile summary for the reports app (written only when SUMMARY_DIR is set) ----
if os.environ.get("SUMMARY_DIR"):
    _D14 = [(FULL_END - D(13 - i)).isoformat() for i in range(14)]
    def _r7(k):
        ks = [(dt.date.fromisoformat(k) - D(j)).isoformat() for j in range(7)]
        v = [0.0] * 10
        for x in ks: v = add(v, day_tot.get(x, [0.0] * 10))
        return round(roas(v) or 0, 2)
    SPARK = [[round(day_tot.get(k, [0] * 10)[0], 2) for k in _D14], [round(day_tot.get(k, [0] * 10)[6], 2) for k in _D14],
             [int(day_tot.get(k, [0] * 10)[5]) for k in _D14], [_r7(k) for k in _D14]]
    t_, m_ = tot["t"], tot["m"]
    json.dump(dict(spark=SPARK, updated=NOW.strftime("%-d %b %Y, %-I:%M %p"), today_date=TODAY.strftime("%-d %b"), t_label=LBL_T.lower(),
                   t_s=t_[0], t_sales=t_[6], t_orders=int(t_[5]), t_roas=roas(t_), m_s=m_[0], m_sales=m_[6], m_orders=int(m_[5]), m_roas=roas(m_), m_profit=profit(m_),
                   active=sum(1 for r in rows if r["act"]), sig=RS["code"] or "hold", sig_label=SIGLBL, reason=RS["why"]),
              open(os.path.join(os.environ["SUMMARY_DIR"], "facebook-tracked.json"), "w"))
