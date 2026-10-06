"""IndiFeels Google Ads Owner Control Centre (report name: GOOGLE ADS TRACKED).

Usage: google_tracked.py DATA.json OUT.html OUT.meta.json [OUT.payload.json]

Three clearly separated stages (data and template never share state except the payload):
  1. compute(raw)   -> payload   (pure calculation, schema tolerant, no HTML)
  2. validate(p)    -> list of problems (publishing is refused if any)
  3. render(p)      -> HTML       (template lives here, in the repository, never in stored data)

Revenue rule: owner revenue = Shopify matched revenue. Google conversion value is shown beside it
as the platform figure. Nothing is estimated: unknown is shown as unknown, never as 0.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")
EXPERT_WEEK = 155.0            # Google Ads expert cost, AUD per week; deducted from account-level profit
FEE_DAY = EXPERT_WEEK / 7
CONTRIB = 0.75 / 1.1          # revenue -> contribution before ad spend: /1.1 removes GST, x0.75 removes 25% product cost
BREAK_EVEN = 1 / CONTRIB      # ROAS at which profit = 0 (about 1.47x)
MIN_SPEND_SIGNAL = 25.0       # below this spend in 7 days the signal is WATCH (too little data)
TIERS_COUNTED = ("Exact", "Strong", "Probable")
PAID_MEDIUMS = {"cpc", "ppc", "pmax", "paid", "paidsearch", "paid_search", "shopping", "demandgen", "demand_gen", "display", "video"}
NOT_PAID_UTM_CAMPAIGNS = {"sag_organic"}
OFFLINE_SOURCES = ("google calls", "google store", "google direction")

D = dt.date


def num(v):
    """Float or None. None is 'unknown' and must never be turned into 0 silently."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def z(v):
    return num(v) or 0.0


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def is_tracked(name):
    n = str(name or "").lower().replace("-", " ").strip()
    return n.startswith("tracked") and not n.startswith("non tracked")


def short_name(n):
    s = str(n or "")
    s = re.sub(r"^Tracked[\s_-]*(MM_)?", "", s, flags=re.I)
    s = re.sub(r"[_\s]*\|?\s*\d{2}[-/]\d{2}[-/]\d{2,4}$", "", s)
    return s.replace("_", " ").strip(" -") or str(n)


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


# --------------------------------------------------------------------------------------
# 1. COMPUTE
# --------------------------------------------------------------------------------------
def compute(raw):
    now = dt.datetime.now(TZ)
    if os.environ.get("GT_NOW"):                       # test hook only; production uses the real clock
        now = dt.datetime.fromisoformat(os.environ["GT_NOW"]).astimezone(TZ)
    today = now.date()
    yday = today - dt.timedelta(days=1)                # previous COMPLETED Melbourne calendar day
    status = raw.get("fetch_status") or {}

    # ---- Google campaign rows (tracked family only; paused campaigns that spent stay visible)
    camps, daily_g = {}, defaultdict(lambda: dict(spend=0.0, impr=0.0, clicks=0.0, conv=0.0, val=0.0))
    cday = defaultdict(dict)                            # campaign id -> date -> row values
    for r in raw.get("campaigns") or []:
        if not is_tracked(r.get("campaign")):
            continue
        try:
            d = D.fromisoformat(str(r.get("date"))[:10])
        except ValueError:
            continue
        cid = str(r.get("campaign_id") or r.get("campaign"))
        c = camps.setdefault(cid, dict(id=cid, name=str(r.get("campaign")), type=None, status=None, budget=None,
                                       first=None, last=None, last_row=None))
        c["name"] = str(r.get("campaign"))
        if r.get("campaign_type"):
            c["type"] = str(r["campaign_type"])
        if c["last"] is None or d >= c["last"]:
            c["last"] = d
            c["status"] = r.get("campaign_status") or c["status"]
            c["budget"] = num(r.get("budget_amount")) if num(r.get("budget_amount")) is not None else c["budget"]
        sp = z(r.get("spend"))
        if sp > 0 and (c["first"] is None or d < c["first"]):
            c["first"] = d
        row = dict(spend=sp, impr=z(r.get("impressions")), clicks=z(r.get("clicks")), conv=z(r.get("conversions")),
                   val=z(r.get("conversions_value")), allv=z(r.get("all_conversions_value")),
                   is_=num(r.get("search_impression_share")), lb=num(r.get("search_budget_lost_impression_share")),
                   lr=num(r.get("search_rank_lost_impression_share")))
        old = cday[cid].get(d)
        if old:  # duplicate rows for a day (segmenting): add additive fields
            for k in ("spend", "impr", "clicks", "conv", "val", "allv"):
                old[k] += row[k]
        else:
            cday[cid][d] = row
    for cid, days in cday.items():
        for d, v in days.items():
            g = daily_g[d]
            for k, kk in (("spend", "spend"), ("impr", "impr"), ("clicks", "clicks"), ("conv", "conv"), ("val", "val")):
                g[kk] += v[k]
    if not camps:
        raise SystemExit("No tracked Google campaigns found in the payload")

    first_spend = min(d for d, v in daily_g.items() if v["spend"] > 0)

    # ---- Shopify orders and attribution
    id_map = {c["id"]: c for c in camps.values()}
    name_norm = {c["id"]: norm(c["name"]) for c in camps.values()}
    spend_days = defaultdict(set)                       # date -> campaign ids that spent
    for cid, days in cday.items():
        for d, v in days.items():
            if v["spend"] > 0:
                spend_days[d].add(cid)

    def visit_signals(o):
        j = o.get("customerJourneySummary") or {}
        out = []
        for k in ("lastVisit", "firstVisit"):
            v = j.get(k) or {}
            u = v.get("utmParameters") or {}
            out.append(dict(kind=k, src=(u.get("source") or v.get("source") or ""), med=(u.get("medium") or ""),
                            camp=(u.get("campaign") or ""), term=(u.get("term") or ""), landing=(v.get("landingPage") or "")))
        return out

    def resolve_campaign(utm):
        """UTM campaign string -> (campaign id, 'Exact'|'Strong') or (None, None)."""
        u = str(utm or "").strip()
        if not u:
            return None, None
        if u in id_map:
            return u, "Exact"
        n = norm(u)
        if not n:
            return None, None
        eq = [cid for cid, nn in name_norm.items() if nn == n]
        if len(eq) == 1:
            return eq[0], "Exact"
        pre = [cid for cid, nn in name_norm.items() if len(n) >= 12 and nn.startswith(n)]
        if len(pre) == 1:
            return pre[0], "Strong"
        return None, None

    def candidates(d):
        s = set(spend_days.get(d, ())) | set(spend_days.get(d - dt.timedelta(days=1), ()))
        return s

    orders, excluded = {}, defaultdict(int)
    for o in raw.get("orders") or []:
        oid = str(o.get("id"))
        if oid in orders:
            excluded["duplicate order id"] += 1
            continue
        try:
            when = dt.datetime.fromisoformat(str(o["processedAt"]).replace("Z", "+00:00")).astimezone(TZ)
        except Exception:
            excluded["unreadable date"] += 1
            continue
        if (o.get("sourceName") or "web") != "web":
            excluded["not a web order (draft/POS/manual)"] += 1
            continue
        gross = z(((o.get("totalPriceSet") or {}).get("shopMoney") or {}).get("amount"))
        cur = num(((o.get("currentTotalPriceSet") or {}).get("shopMoney") or {}).get("amount"))
        refunded = z(((o.get("totalRefundedSet") or {}).get("shopMoney") or {}).get("amount"))
        net = max(0.0, (cur if cur is not None else gross - refunded))
        cancelled = bool(o.get("cancelledAt"))
        src = ((o.get("m") or {}).get("value") or "")
        sigs = visit_signals(o)
        paid = None
        for s in sigs:
            if s["src"].lower() in ("google", "google-ads", "googleads", "google ads", "adwords") and \
               (s["med"].lower() in PAID_MEDIUMS) and s["camp"] not in NOT_PAID_UTM_CAMPAIGNS:
                paid = s
                break
        gclid = any("gclid=" in s["landing"] for s in sigs)
        src_google = src.lower().startswith("google online") or src.lower().startswith("google ads")
        offline = any(src.lower().startswith(p) for p in OFFLINE_SOURCES)
        rec = dict(id=oid, name=o.get("name"), date=when.date(), net=net, gross=gross, refunded=refunded,
                   cancelled=cancelled, status=o.get("displayFinancialStatus"), source=src, utm=(paid or {}).get("camp"),
                   term=(paid or {}).get("term"), tier="Unmatched", camp=None, why="", counted=False, offline=offline,
                   trk=bool(paid or gclid), has_utm=bool(paid), gclid=gclid, src_google=src_google,
                   sub=num(((o.get("currentSubtotalPriceSet") or {}).get("shopMoney") or {}).get("amount")))
        # --- tiers
        if cancelled:
            rec["why"] = "Cancelled: excluded from revenue"
        elif offline:
            rec["why"] = "Google calls / store visit: not trackable to a campaign (informational)"
        elif paid or gclid or src_google:
            cid, t = (resolve_campaign(paid["camp"]) if paid else (None, None))
            conflict = bool(src) and not src_google and src.lower() not in ("organic orders", "invalid", "none")
            if cid:
                rec.update(camp=cid, tier=("Strong" if (conflict and t == "Exact") else t), counted=True,
                           why="UTM campaign resolves to this campaign" + (" (order source says otherwise; kept as Strong)" if conflict else ""))
            elif paid and conflict:
                rec["why"] = "Google UTM but order source is another channel (" + src + "): excluded, not forced"
            else:
                cand = candidates(rec["date"])
                basis = "Google click evidence in UTM/gclid" if (paid or gclid) else 'order source "Google Online Orders"'
                if cand:
                    rec.update(tier="Probable", counted=True)
                    if len(cand) == 1:
                        only = next(iter(cand))
                        rec.update(camp=only, why=basis + "; the only tracked campaign spending that day, so assigned to it (inferred)")
                    else:
                        rec["why"] = basis + "; several tracked campaigns spending, so campaign left Unattributed"
                else:
                    rec["why"] = basis + ", but no tracked campaign was spending: not counted"
        else:
            rec["why"] = "No Google signal (" + (src or "no source") + ")"
        orders[oid] = rec

    ordl = list(orders.values())
    first_order = min((o["date"] for o in ordl), default=None)
    if first_order is None:
        raise SystemExit("No usable Shopify orders")
    life_start = max(first_spend, first_order)

    def counted(o):
        return o["counted"] and not o["cancelled"]

    # ---- period aggregation
    W = {
        "yesterday": (yday, yday), "7": (yday - dt.timedelta(days=6), yday),
        "15": (yday - dt.timedelta(days=14), yday), "30": (yday - dt.timedelta(days=29), yday), "life": (life_start, yday),
    }
    PREV = {"yesterday": (yday - dt.timedelta(days=1),) * 2, "7": (yday - dt.timedelta(days=13), yday - dt.timedelta(days=7)),
            "15": (yday - dt.timedelta(days=29), yday - dt.timedelta(days=15)),
            "30": (yday - dt.timedelta(days=59), yday - dt.timedelta(days=30))}
    LABEL = {"yesterday": "Yesterday", "7": "Last 7 days", "15": "Last 15 days", "30": "Last 30 days", "life": "Lifetime"}

    def agg(a, b, cid=None):
        r = dict(spend=0.0, impr=0.0, clicks=0.0, conv=0.0, gval=0.0, orders=0, rev=0.0, exact=0, strong=0, prob=0,
                 camp_orders=0, camp_rev=0.0, un_orders=0, un_rev=0.0,
                 fee=(FEE_DAY * ((b - a).days + 1) if cid is None else 0.0))
        if cid is None:
            for d in daterange(a, b):
                g = daily_g.get(d)
                if g:
                    r["spend"] += g["spend"]; r["impr"] += g["impr"]; r["clicks"] += g["clicks"]; r["conv"] += g["conv"]; r["gval"] += g["val"]
        else:
            for d in daterange(a, b):
                g = cday[cid].get(d)
                if g:
                    r["spend"] += g["spend"]; r["impr"] += g["impr"]; r["clicks"] += g["clicks"]; r["conv"] += g["conv"]; r["gval"] += g["val"]
        for o in ordl:
            if not counted(o) or not (a <= o["date"] <= b):
                continue
            if cid is not None and o["camp"] != cid:
                continue
            r["orders"] += 1; r["rev"] += o["net"]
            r[{"Exact": "exact", "Strong": "strong", "Probable": "prob"}[o["tier"]]] += 1
            if o["camp"]:
                r["camp_orders"] += 1; r["camp_rev"] += o["net"]
            else:
                r["un_orders"] += 1; r["un_rev"] += o["net"]
        return fin(r)

    def fin(r):
        r["profit"] = r["rev"] * CONTRIB - r["spend"] - r.get("fee", 0.0)
        r["gprofit"] = r["gval"] * CONTRIB - r["spend"] - r.get("fee", 0.0)
        r["roas"] = r["rev"] / r["spend"] if r["spend"] > 0 else None
        r["groas"] = r["gval"] / r["spend"] if r["spend"] > 0 else None
        r["ctr"] = r["clicks"] / r["impr"] if r["impr"] > 0 else None
        r["cpc"] = r["spend"] / r["clicks"] if r["clicks"] > 0 else None
        r["cvr"] = r["conv"] / r["clicks"] if r["clicks"] > 0 else None
        r["cpa"] = r["spend"] / r["orders"] if r["orders"] > 0 else None
        r["aov"] = r["rev"] / r["orders"] if r["orders"] > 0 else None
        r["match_orders"] = (min(r["orders"], r["conv"]) / max(r["orders"], r["conv"])) if max(r["orders"], r["conv"]) > 0 else None
        r["match_rev"] = (min(r["rev"], r["gval"]) / max(r["rev"], r["gval"])) if max(r["rev"], r["gval"]) > 0 else None
        return r

    periods = {k: agg(*v) for k, v in W.items()}
    prev = {k: agg(*v) for k, v in PREV.items()}
    for k in prev:
        prev[k]["from"] = PREV[k][0].isoformat(); prev[k]["to"] = PREV[k][1].isoformat()
    for k in periods:
        periods[k]["from"] = W[k][0].isoformat(); periods[k]["to"] = W[k][1].isoformat(); periods[k]["label"] = LABEL[k]

    # ---- tracked (Shopify saw the Google click: paid UTM or gclid) vs non-tracked (counted only through custom.order_source)
    trk = {}
    for k, (a, b) in W.items():
        t_o = [o for o in ordl if counted(o) and a <= o["date"] <= b]
        tr = [o for o in t_o if o["trk"]]; nt = [o for o in t_o if not o["trk"]]
        gv = periods[k]["gval"]; tot = sum(o["net"] for o in t_o)
        trk[k] = dict(g_val=gv, g_conv=periods[k]["conv"], t_orders=len(tr), t_rev=sum(o["net"] for o in tr), n_orders=len(nt), n_rev=sum(o["net"] for o in nt),
                      total_orders=len(t_o), total_rev=tot, accuracy=(min(tot, gv) / max(tot, gv)) if max(tot, gv) > 0 else None,
                      tracked_share=(sum(o["net"] for o in tr) / tot) if tot > 0 else None)

    # ---- tracking confidence (guardrail): uses the last 30 completed days
    def confidence(p):
        if p["conv"] < 5 and p["orders"] < 5:
            return "Insufficient", "Fewer than 5 conversions or matched orders in the window."
        mo, mr = p["match_orders"], p["match_rev"]
        if mo is None or mr is None:
            return "Insufficient", "Nothing to compare yet."
        exact_share = (p["exact"] + p["strong"]) / p["orders"] if p["orders"] else 0
        score = min(mo, mr)
        if score >= 0.8 and exact_share >= 0.5:
            return "High", "Matched orders and revenue are within about 20% of Google."
        if score >= 0.5:
            return "Medium", "Shopify matches about {:.0f}% of what Google reports; owner ROAS is a floor, not exact.".format(score * 100)
        return "Low", "Shopify matches only about {:.0f}% of what Google reports; treat owner ROAS as a floor.".format(score * 100)
    conf, conf_why = confidence(periods["30"])

    # ---- daily series
    days = []
    for d in daterange(life_start, yday):
        g = daily_g.get(d, dict(spend=0.0, impr=0.0, clicks=0.0, conv=0.0, val=0.0))
        mo = [o for o in ordl if counted(o) and o["date"] == d]
        rev = sum(o["net"] for o in mo)
        days.append(dict(date=d.isoformat(), spend=g["spend"], clicks=g["clicks"], impr=g["impr"], conv=g["conv"], gval=g["val"],
                         orders=len(mo), rev=rev, fee=FEE_DAY, profit=rev * CONTRIB - g["spend"] - FEE_DAY, gprofit=g["val"] * CONTRIB - g["spend"] - FEE_DAY))
    cum, run = [], 0.0
    for x in days:
        run += x["profit"]; cum.append(round(run, 2))

    # ---- month-to-date (completed days only) and velocity
    mstart = D(yday.year, yday.month, 1) if today.day > 1 else None
    mtd = agg(max(mstart, life_start), yday) if mstart else None
    mtd_label = None
    if mstart:
        mtd_label = "MTD / partial month · {}–{} {}".format(mstart.strftime("%-d"), yday.strftime("%-d %b"), yday.strftime("%Y"))

    def pctchg(cur, old):
        if old is None or abs(old) < 1e-9:
            return None
        return (cur - old) / abs(old)
    vel7 = periods["7"]["profit"] / 7
    vel7p = prev["7"]["profit"] / 7
    vel30 = periods["30"]["profit"] / 30
    vel30p = prev["30"]["profit"] / 30
    pm_end = (D(yday.year, yday.month, 1) - dt.timedelta(days=1)) if mstart else (D(yday.year, yday.month, 1) - dt.timedelta(days=1)) if yday.day == 1 else None
    pace_rows = []

    def prow_(label, r, n, prev_r, prev_n):
        if r is None:
            return
        per = r["profit"] / n if n else None
        pper = (prev_r["profit"] / prev_n) if (prev_r is not None and prev_n) else None
        pace_rows.append(dict(label=label, profit=r["profit"], per_day=per, change=pctchg(per, pper) if (per is not None and pper is not None) else None, days=n))
    prow_("Last 7 days", periods["7"], 7, prev["7"], 7)
    prow_("Previous 7 days", prev["7"], 7, None, 0)
    prow_("Last 30 days", periods["30"], 30, prev["30"], 30)
    prow_("Previous 30 days", prev["30"], 30, None, 0)
    if mtd is not None:
        nd = (yday - max(mstart, life_start)).days + 1
        pm_start = D(pm_end.year, pm_end.month, 1) if pm_end else None
        pmr = agg(max(pm_start, life_start), pm_end) if (pm_start and pm_end >= life_start) else None
        pmn = ((pm_end - max(pm_start, life_start)).days + 1) if pmr else 0
        prow_("This month (MTD)", mtd, nd, pmr, pmn)
        if pmr:
            prow_("Previous month", pmr, pmn, None, 0)
    velocity = dict(d7=vel7, d7_prev=vel7p, d7_chg=pctchg(vel7, vel7p), d30=vel30, d30_prev=vel30p, d30_chg=pctchg(vel30, vel30p))

    # ---- campaigns by window
    camp_rows = {}
    for k, (a, b) in W.items():
        rows = []
        for cid, c in camps.items():
            r = agg(a, b, cid)
            if r["spend"] <= 0 and r["conv"] <= 0 and r["orders"] <= 0:
                continue
            ds = [cday[cid][d] for d in daterange(a, b) if d in cday[cid]]
            imps = sum(x["impr"] for x in ds if x["is_"] is not None)

            def wavg(key):
                vals = [(x[key], x["impr"]) for x in ds if x[key] is not None and x["impr"] > 0]
                w = sum(i for _, i in vals)
                return (sum(v * i for v, i in vals) / w) if w > 0 else None
            r.update(id=cid, name=c["name"], short=short_name(c["name"]), type=c["type"], status=c["status"], budget=c["budget"],
                     is_=wavg("is_"), lb=wavg("lb"), lr=wavg("lr"))
            rows.append(r)
        rows.sort(key=lambda r: -r["spend"])
        camp_rows[k] = rows

    # ---- budget signal
    reasons, p7, p30 = [], periods["7"], periods["30"]
    sig, headline = "WATCH", ""
    google_ok = p7["spend"] > 0 or p30["spend"] > 0
    last_g = max([d for d in daily_g if d <= yday] or [max(daily_g)])
    stale = (yday - last_g).days
    if stale >= 2:
        sig, headline = "FIX TRACKING", f"Google data is {stale} days old; completed data should reach {yday.strftime('%-d %b')}."
        reasons.append(headline)
    elif p7["spend"] < MIN_SPEND_SIGNAL:
        sig, headline = "WATCH", f"Only ${p7['spend']:.0f} spent in the last 7 days; too little to judge."
        reasons.append(headline)
    else:
        r7, r30 = p7["roas"], p30["roas"]
        gr7 = p7["groas"]
        low_conf = conf in ("Low", "Insufficient")
        constrained = [c for c in camp_rows["7"] if c["lb"] is not None and c["lb"] >= 0.10 and c["roas"] is not None and c["roas"] >= BREAK_EVEN]
        if r7 is not None and r7 < BREAK_EVEN and gr7 is not None and gr7 >= BREAK_EVEN and low_conf:
            sig, headline = "FIX TRACKING", f"Shopify shows {r7:.2f}x but Google shows {gr7:.2f}x and only part of Google's conversions can be matched, so the owner number is unreliable."
        elif p7["profit"] <= 0 and (p30["profit"] <= 0 or vel7 < vel7p):
            sig, headline = "REDUCE", f"Last 7 days lost ${abs(p7['profit']):.0f} after the $155 expert fee (ROAS {r7:.2f}x vs ad-only break-even {BREAK_EVEN:.2f}x) and the trend is not improving."
        elif p7["profit"] <= 0:
            sig, headline = "WATCH", f"Last 7 days is ${abs(p7['profit']):.0f} below break-even after the $155 expert fee, but the 30-day view is still profitable."
        elif r7 >= BREAK_EVEN * 1.4 and p30["profit"] > 0 and constrained and not low_conf:
            sig, headline = "SCALE", "Profitable on 7 and 30 days and held back by budget on: " + ", ".join(c["short"] for c in constrained[:2]) + "."
        elif r7 >= BREAK_EVEN * 1.4 and p30["profit"] > 0:
            sig, headline = "HOLD", f"Profitable (ROAS {r7:.2f}x vs break-even {BREAK_EVEN:.2f}x) with no budget constraint to unlock."
        else:
            sig, headline = "HOLD", f"Above break-even ({r7:.2f}x vs {BREAK_EVEN:.2f}x) but with thin margin; keep budget steady."
        reasons.append(headline)
        reasons.append(f"7-day owner ROAS {r7:.2f}x" + (f" vs Google {gr7:.2f}x" if gr7 is not None else "") + f"; break-even {BREAK_EVEN:.2f}x.")
        reasons.append(f"Profit velocity ${vel7:,.0f}/day ({'' if velocity['d7_chg'] is None else format(velocity['d7_chg'] * 100, '+.0f') + '%'} vs previous 7 days).")
        if sig == "SCALE" and low_conf:
            sig = "HOLD"
        reasons.append(f"Tracking confidence {conf}: {conf_why}" + (" SCALE is blocked while confidence is low." if low_conf else ""))
    signal = dict(code=sig, headline=headline, reasons=reasons)

    # ---- drilldown tables
    def sumrows(rows, keys):
        out = defaultdict(lambda: dict(spend=0.0, impr=0.0, clicks=0.0, conv=0.0, val=0.0))
        for r in rows or []:
            k = tuple(str(r.get(x) or "") for x in keys)
            o = out[k]
            for f, ff in (("spend", "spend"), ("impressions", "impr"), ("clicks", "clicks"), ("conversions", "conv"), ("conversions_value", "val")):
                o[ff] += z(r.get(f))
        return out

    def mk(rows, keys, extra):
        res = []
        for k, v in sumrows(rows, keys).items():
            d = dict(zip(keys, k))
            d.update(v)
            d.update(extra(d))
            d["ctr"] = v["clicks"] / v["impr"] if v["impr"] > 0 else None
            d["cpc"] = v["spend"] / v["clicks"] if v["clicks"] > 0 else None
            d["cvr"] = v["conv"] / v["clicks"] if v["clicks"] > 0 else None
            d["groas"] = v["val"] / v["spend"] if v["spend"] > 0 else None
            res.append(d)
        res.sort(key=lambda d: -d["spend"])
        return res
    drill = {}
    for ent, keys in (("adgroups", ("campaign_id", "ad_group_name")), ("keywords", ("campaign_id", "ad_group_name", "keyword_text", "keyword_match_type")),
                      ("search_terms", ("campaign_id", "ad_group_name", "search_term"))):
        src = raw.get(ent) or {}
        drill[ent] = {}
        for w, wk in (("7", "last7"), ("15", "last15"), ("30", "last30"), ("life", "lifetime")):
            rows = src.get(wk)
            if rows is None:
                drill[ent][w] = None                         # source failed: shown as unavailable
                continue
            rows = [r for r in rows if str(r.get("campaign_id")) in camps and (ent == "adgroups" and r.get("ad_group_name")
                    or ent != "adgroups" and r.get("search_term" if ent == "search_terms" else "keyword_text"))]
            drill[ent][w] = mk(rows, keys, lambda d: {})
    # PMax / non-search rows have no ad group names; handled in render.

    # ---- waste (search terms, 30d falling back to lifetime)
    waste, waste_win = [], None
    for w in ("30", "life"):
        st = drill["search_terms"].get(w)
        if st:
            waste_win = w
            brand = lambda t: bool(re.search(r"indi\s?feels", t, re.I))
            waste = [dict(t, brand=brand(t["search_term"])) for t in st if t["spend"] >= 5 and t["conv"] == 0]
            break
    waste_total = sum(t["spend"] for t in waste)

    # ---- order tables
    def order_row(o):
        return dict(name=o["name"], date=o["date"].isoformat(), net=o["net"], tier=o["tier"], camp=(camps[o["camp"]]["name"] if o["camp"] else None),
                    why=o["why"], source=o["source"], counted=o["counted"], cancelled=o["cancelled"], status=o["status"], term=o["term"],
                    trk=o["trk"], has_utm=o["has_utm"], utm=o["utm"], gclid=o["gclid"], src_google=o["src_google"])
    googleish = [o for o in ordl if o["tier"] != "Unmatched" or o["utm"] or "google" in o["source"].lower()]
    googleish.sort(key=lambda o: (o["date"], o["name"] or ""), reverse=True)
    order_table = [order_row(o) for o in googleish if o["date"] >= W["30"][0]][:150]
    unresolved_utms = defaultdict(int)
    for o in ordl:
        if o["utm"] and not o["camp"] and o["counted"]:
            unresolved_utms[o["utm"]] += 1

    # ---- Google conversions (by conversion date) matched to Shopify orders by value
    # Google's conversion value is the order SUBTOTAL (total minus shipping). Google exposes no order id, so a match is a possible
    # match: same value on the same day, else the day either side. Informational only: it never changes revenue or profit.
    import itertools
    groups = []
    for r in raw.get("conversions_daily") or []:
        cid = str(r.get("campaign_id"))
        if cid not in camps:
            continue
        try:
            d = D.fromisoformat(str(r.get("date"))[:10])
        except ValueError:
            continue
        n_, v_ = z(r.get("conversions_by_conversion_date")), z(r.get("conversions_value_by_conversion_date"))
        if n_ <= 0 and v_ <= 0:
            continue
        groups.append(dict(date=d, cid=cid, k=max(1, round(n_)), tot=v_))
    groups.sort(key=lambda g: (g["date"], -g["tot"]))
    used = set()
    SHIP = (0.0, 8.0, 10.0, 18.0)
    def fits(o, val):
        """Google's value is the order subtotal. Use it when Shopify gave it; otherwise allow total less a usual shipping fee."""
        if o["sub"] is not None:
            return abs(o["sub"] - val) <= 0.99
        return any(abs((o["net"] - sh) - val) <= 0.5 for sh in SHIP)
    def pool(g):
        return [o for o in ordl if o["id"] not in used and not o["cancelled"] and o["net"] > 0 and abs((o["date"] - g["date"]).days) <= 1]
    def pref(o, g, val):
        dd = abs((o["date"] - g["date"]).days)
        return (dd, 0 if (counted(o) and o["camp"] == g["cid"]) else (1 if counted(o) else 2),
                abs(o["sub"] - val) if o["sub"] is not None else 0.0)
    gm = []
    def emit(g, val, o, ncand):
        row = dict(date=g["date"].isoformat(), cid=g["cid"], camp=camps[g["cid"]]["name"], val=val, ncand=ncand)
        if o is None:
            row.update(order=None, res="none")
        else:
            used.add(o["id"])
            res = ("counted" if (o["camp"] in (None, g["cid"])) else "other_campaign") if counted(o) else "missing"
            row.update(order=o["name"], odate=o["date"].isoformat(), onet=o["net"], osub=o["sub"], source=o["source"], utm=bool(o["utm"]), trk=o["trk"],
                       tier=o["tier"], ocamp=(camps[o["camp"]]["name"] if o["camp"] else None), counted=counted(o), why=o["why"], res=res)
        gm.append(row)
    for g in groups:
        if g["k"] == 1:
            c = [o for o in pool(g) if fits(o, g["tot"])]
            c.sort(key=lambda o: pref(o, g, g["tot"]))
            emit(g, g["tot"], c[0] if c else None, len(c))
            continue
        # several conversions on one day for one campaign: look for orders whose values add up to Google's total
        found = None
        cand = [o for o in pool(g)]
        for combo in itertools.combinations(cand, g["k"]):
            if g["k"] > 3:
                break
            if all(o["sub"] is not None for o in combo):
                ok = abs(sum(o["sub"] for o in combo) - g["tot"]) <= 0.99 * g["k"]
            else:
                ok = any(abs(sum(o["net"] for o in combo) - sum(sh) - g["tot"]) <= 0.5 for sh in itertools.product(SHIP, repeat=g["k"]))
            if ok:
                key = tuple(sorted(pref(o, g, g["tot"] / g["k"]) for o in combo))
                if found is None or key < found[0]:
                    found = (key, combo)
        if found:
            tot_net = sum(o["net"] for o in found[1])
            for o in found[1]:
                emit(g, (o["sub"] if o["sub"] is not None else g["tot"] * o["net"] / tot_net), o, 1)
        else:
            for _ in range(g["k"]):
                emit(g, g["tot"] / g["k"], None, 0)
    gsum = {}
    for k, (a, b) in W.items():
        rows_ = [g for g in gm if a <= D.fromisoformat(g["date"]) <= b]
        def part(f):
            xs = [x for x in rows_ if f(x)]
            return len(xs), sum(x["val"] for x in xs)
        c_all = lambda x: x["res"] in ("counted", "other_campaign")
        n_ct, v_ct = part(lambda x: c_all(x) and x["trk"]); n_cn, v_cn = part(lambda x: c_all(x) and not x["trk"])
        n_mu, v_mu = part(lambda x: x["res"] == "missing" and not x["utm"]); n_mx, v_mx = part(lambda x: x["res"] == "missing" and x["utm"])
        n_no, v_no = part(lambda x: x["res"] == "none")
        cw = [o for o in ordl if counted(o) and a <= o["date"] <= b]
        extra = [o for o in cw if o["id"] not in used]; mc = [o for o in cw if o["id"] in used]
        gsum[k] = dict(n=len(rows_), val=sum(x["val"] for x in rows_), n_counted=n_ct + n_cn, v_counted=v_ct + v_cn, n_missing=n_mu + n_mx, v_missing=v_mu + v_mx, n_none=n_no, v_none=v_no,
                       n_ct=n_ct, v_ct=v_ct, n_cn=n_cn, v_cn=v_cn, n_mu=n_mu, v_mu=v_mu, n_mx=n_mx, v_mx=v_mx,
                       n_extra=len(extra), v_extra=sum(o["net"] for o in extra), n_mc=len(mc), v_mc=sum(o["net"] for o in mc), our_rev=sum(o["net"] for o in cw))
    gmatch = [g for g in gm if g["date"] >= W["30"][0].isoformat()][::-1]

    # ---- month -> day tracking
    months = []
    bym = defaultdict(list)
    for x in days:
        bym[x["date"][:7]].append(x)
    for m in sorted(bym, reverse=True):
        xs = bym[m]
        t = {k: sum(x[k] for x in xs) for k in ("spend", "clicks", "impr", "conv", "gval", "orders", "rev", "profit", "gprofit")}
        months.append(dict(month=m, days=sorted(xs, key=lambda x: x["date"], reverse=True), **t))

    # ---- orders still waiting for an attribution (custom.order_source empty): for reference, see the order attribution report
    def _wait(a_, b_):
        w = [o for o in ordl if not o["cancelled"] and not o.get("source") and a_ <= o["date"] <= b_]
        return dict(n=len(w), rev=sum(o["net"] for o in w))
    waiting = dict(yesterday=_wait(yday, yday), today=_wait(today, today), d7=_wait(W["7"][0], today))

    # ---- today (partial, never replaces yesterday)
    g0 = daily_g.get(today)
    today_orders = [o for o in ordl if counted(o) and o["date"] == today]
    today_block = dict(date=today.isoformat(), spend=(g0 or {}).get("spend"), clicks=(g0 or {}).get("clicks"), conv=(g0 or {}).get("conv"),
                       gval=(g0 or {}).get("val"), orders=len(today_orders), rev=sum(o["net"] for o in today_orders), has_google=g0 is not None)

    # ---- data status
    last_order = max(ordl, key=lambda o: o["date"])["date"]
    total_matched_orders = sum(1 for o in ordl if counted(o))
    camp_attr = sum(1 for o in ordl if counted(o) and o["camp"])
    attribution = dict(total=total_matched_orders, with_campaign=camp_attr, unattributed=total_matched_orders - camp_attr,
                       exact=sum(1 for o in ordl if counted(o) and o["tier"] == "Exact"), strong=sum(1 for o in ordl if counted(o) and o["tier"] == "Strong"),
                       probable=sum(1 for o in ordl if counted(o) and o["tier"] == "Probable"),
                       cancelled=sum(1 for o in ordl if o["cancelled"]), excluded=dict(excluded),
                       conflicts=sum(1 for o in ordl if (not o["counted"]) and o["utm"] and not o["cancelled"] and W["30"][0] <= o["date"] <= W["30"][1]),
                       offline=sum(1 for o in ordl if o["offline"]))

    # ---- issues and actions (from real numbers only)
    issues, actions = [], []

    def issue(sev, what, why, act):
        issues.append(dict(sev=sev, what=what, why=why, action=act))
        actions.append(dict(sev=sev, action=act, why=what))
    if conf in ("Low", "Medium"):
        gapn = max(0.0, p30["conv"] - p30["orders"])
        gapr = max(0.0, p30["gval"] - p30["rev"])
        issue("amber" if conf == "Medium" else "red",
              f"Google reports {p30['conv']:.0f} conversions worth ${p30['gval']:,.0f}; Shopify matched {p30['orders']} orders worth ${p30['rev']:,.0f} (last 30 days).",
              f"About {gapn:.0f} conversions / ${gapr:,.0f} cannot be tied to a Shopify order, so owner ROAS is a floor.",
              "Make sure every tracked campaign has the UTM template (utm_source=google, utm_medium=cpc, utm_campaign={campaignid}) so orders can be matched exactly.")
    if attribution["unattributed"] > 0:
        issue("amber", f"{attribution['unattributed']} matched orders (${sum(o['net'] for o in ordl if counted(o) and not o['camp']):,.0f}) have a Google signal but no campaign.",
              "They count in the total but cannot be credited to a campaign.", "Add the campaign id to the final URL suffix on Performance Max, Shopping and Demand Gen campaigns.")
    if waste_total > 0:
        issue("amber", f"${waste_total:,.0f} spent on {len(waste)} search terms with no conversions ({'last 30 days' if waste_win=='30' else 'lifetime'}).",
              "Non-converting spend lowers profit.", "Review the non-brand terms below as negative-keyword candidates.")
    for m in months[:4]:
        if m["spend"] >= 100 and m["gval"] >= 2 * max(m["rev"], 1):
            issue("red", f"{dt.date.fromisoformat(m['month'] + '-01').strftime('%B')}: Google reports ${m['gval']:,.0f} of conversion value but Shopify matched only ${m['rev']:,.0f} on ${m['spend']:,.0f} spend.",
                  "Owner profit that month is understated or Google is over-counting; either way the month cannot be trusted.",
                  "Compare that month's Google conversion actions with real Shopify orders and check for missing UTM tags on the campaigns that ran.")
    for c in camp_rows["30"]:
        if c["spend"] >= 25 and c["rev"] <= 0:
            issue("red", f"{c['short']} spent ${c['spend']:,.0f} in 30 days with no matched Shopify revenue.", "Pure loss on the owner view" + (f" (Google claims ${c['gval']:,.0f})." if c["gval"] > 0 else "."),
                  "Check the landing page, product feed and tracking for this campaign before spending more.")
        elif c["roas"] is not None and c["roas"] < BREAK_EVEN and c["spend"] >= 50 and c["status"] == "ENABLED":
            issue("amber", f"{c['short']} ROAS {c['roas']:.2f}x is below break-even {BREAK_EVEN:.2f}x on ${c['spend']:,.0f} spend (30 days).", f"Loses about ${abs(c['profit']):,.0f} on the owner view.",
                  "Lower its budget or tighten targeting; re-check once tracking is complete.")
    for c in camp_rows["7"]:
        if c["lb"] is not None and c["lb"] >= 0.10 and c["roas"] is not None and c["roas"] >= BREAK_EVEN and c["status"] == "ENABLED":
            issue("green", f"{c['short']} is profitable and loses {c['lb']*100:.0f}% of impressions to budget (7 days).", "More budget could capture profitable demand.",
                  f"Test raising its daily budget (now {('$'+format(c['budget'],',.0f')) if c['budget'] else 'unknown'}) by about 20% and watch profit velocity for 3 days.")
    if not issues:
        issues.append(dict(sev="green", what="No issues found in the current data.", why="Tracking and performance checks all passed.", action="Keep monitoring."))
    sev_order = {"red": 0, "amber": 1, "green": 2}
    issues.sort(key=lambda i: sev_order[i["sev"]])
    actions = [dict(sev=i["sev"], action=i["action"], why=i["what"]) for i in issues if i["action"] != "Keep monitoring."]

    # ---- reconciliation (Google vs Shopify) per window
    recon = {}
    for k in ("yesterday", "7", "15", "30", "life"):
        p = periods[k]
        recon[k] = dict(g_conv=p["conv"], s_orders=p["orders"], g_val=p["gval"], s_rev=p["rev"], d_orders=p["orders"] - p["conv"], d_rev=p["rev"] - p["gval"],
                        match_orders=p["match_orders"], match_rev=p["match_rev"], camp_orders=p["camp_orders"], un_orders=p["un_orders"],
                        camp_rev=p["camp_rev"], un_rev=p["un_rev"], exact=p["exact"], strong=p["strong"], prob=p["prob"],
                        google_unmatched=max(0.0, p["conv"] - p["orders"]), shopify_unmatched=max(0.0, p["orders"] - p["conv"]))


    # ======================= FB-style table: entities, health, rank, signal, flags =======================
    MINSP = 20.0
    orev = defaultdict(lambda: defaultdict(float))     # campaign id (or "") -> date -> owner revenue
    oord = defaultdict(lambda: defaultdict(int))
    for o in ordl:
        if counted(o):
            orev[o["camp"] or ""][o["date"]] += o["net"]; oord[o["camp"] or ""][o["date"]] += 1

    def ent_days(cid):
        out = {}
        for d, v in cday[cid].items():
            out[d] = dict(spend=v["spend"], rev=orev[cid].get(d, 0.0), gval=v["val"], conv=v["conv"], clicks=v["clicks"], impr=v["impr"], orders=oord[cid].get(d, 0))
        for d, r in orev[cid].items():
            out.setdefault(d, dict(spend=0.0, rev=r, gval=0.0, conv=0.0, clicks=0.0, impr=0.0, orders=oord[cid].get(d, 0)))
        return out

    def ewin(days, a, b, basis):
        r = dict(spend=0.0, rev=0.0, gval=0.0, conv=0.0, clicks=0.0, impr=0.0, orders=0)
        for d, x in days.items():
            if a <= d <= b:
                for k in r:
                    r[k] += x.get(k, 0)
        base = r["rev"] if basis == "owner" else r["gval"]
        r["base"] = base
        r["profit"] = base * CONTRIB - r["spend"]
        r["roas"] = base / r["spend"] if r["spend"] > 0 else None
        r["groas"] = r["gval"] / r["spend"] if r["spend"] > 0 else None
        r["cvr"] = r["conv"] / r["clicks"] if r["clicks"] > 0 else None
        r["ctr"] = r["clicks"] / r["impr"] if r["impr"] > 0 else None
        r["cpc"] = r["spend"] / r["clicks"] if r["clicks"] > 0 else None
        return r

    H = {k: W[k] for k in ("7", "15", "30")}

    def emetrics(days, active, basis):
        m = {"basis": basis}
        for k in ("yesterday", "7", "15", "30", "life"):
            m[k] = ewin(days, *W[k], basis)
            if k in PREV:
                m["p" + k] = ewin(days, *PREV[k], basis)
        def wroas(a_, b_):
            xs = [x for d, x in days.items() if a_ <= d <= b_]
            sp = sum(x["spend"] for x in xs); bs = sum((x["rev"] if basis == "owner" else x["gval"]) for x in xs)
            return (bs / sp if sp >= MINSP else None, sp)
        m["h7"], m["h15"], m["h30"] = wroas(*H["7"]), wroas(*H["15"]), wroas(*H["30"])
        allsp = sorted(d for d, x in days.items() if x["spend"] > 0 and W["life"][0] <= d <= yday)
        m["lh"] = wroas(W["life"][0], yday)
        m["nspend"] = len(allsp)
        m["ls"] = allsp[-1] if allsp else None
        if allsp:
            run = [allsp[-1]]
            for d in reversed(allsp[:-1]):
                if (run[-1] - d).days > 3:
                    break
                run.append(d)
            m["lr"] = wroas(min(run), max(run))
        else:
            m["lr"] = (None, 0.0)
        m["act"] = active
        s30, r30 = m["30"]["spend"], m["30"]["base"]
        ro30, ro7 = m["h30"][0], m["h7"][0]
        if not active:
            m["health"] = ("none", "Paused")
        elif s30 < MINSP:
            m["health"] = ("none", "New")
        elif r30 <= 0 or (ro30 is not None and ro30 < BREAK_EVEN):
            m["health"] = ("r", "Poor")
        elif ro30 is not None and ro30 >= BREAK_EVEN * 1.2 and (ro7 is None or ro7 >= BREAK_EVEN):
            m["health"] = ("g", "Good")
        else:
            m["health"] = ("y", "Watch")
        return m

    def pctl(vals, hg):
        ids = list(vals); n = len(ids)
        if n == 1:
            return {ids[0]: 1.0}
        out = {}
        for i in ids:
            worse = sum(1 for j in ids if j != i and ((vals[j] < vals[i]) if hg else (vals[j] > vals[i])))
            tie = sum(1 for j in ids if j != i and vals[j] == vals[i])
            out[i] = (worse + 0.5 * tie) / (n - 1)
        return out

    def rank_group(ms):
        """Score = 70% profit $ + 30% ROAS (percentiles among peers). Final = 60% last 30 days + 40% last 7. Under $20 spend in a window = not ranked there."""
        def score(win):
            el = {i: v[win] for i, v in ms.items() if v[win]["spend"] >= MINSP}
            if not el:
                return {}
            a = pctl({i: v["profit"] for i, v in el.items()}, True)
            b = pctl({i: (v["roas"] or 0) for i, v in el.items()}, True)
            return {i: 0.7 * a[i] + 0.3 * b[i] for i in el}
        s30, s15, s7 = score("30"), score("15"), score("7")
        fin = {i: (0.6 * s30[i] + 0.4 * s7[i] if i in s7 else s30[i]) for i in s30}
        order = sorted(fin, key=lambda i: (-fin[i], -ms[i]["30"]["profit"]))
        o = lambda sc, k: sorted(sc, key=lambda i: (-sc[i], -ms[i][k]["profit"]))
        o7, o15, o30 = o(s7, "7"), o(s15, "15"), o(s30, "30")
        return {i: dict(rank=order.index(i) + 1, n=len(order), r7=(o7.index(i) + 1 if i in s7 else None), r15=(o15.index(i) + 1 if i in s15 else None),
                        r30=o30.index(i) + 1, n7=len(o7), n15=len(o15), n30=len(o30), sc=round(fin[i] * 100), sc7=(round(s7[i] * 100) if i in s7 else None), sc15=(round(s15[i] * 100) if i in s15 else None), sc30=round(s30[i] * 100)) for i in order}

    def sig_for(m, gap=None):
        if not m["act"]:
            return None
        a7, a30 = m["7"], m["30"]
        if a30["spend"] < MINSP and a7["spend"] < MINSP:
            return ("hold", "Hold", "Too little spend to judge yet")
        if gap:
            return ("hold", "Hold", gap)
        if m["health"][0] == "r":
            return ("down", "Spend less", "Health is poor")
        if a7["spend"] >= MINSP and a7["roas"] is not None and a7["roas"] < BREAK_EVEN:
            return ("down", "Spend less", f"7-day ROAS {a7['roas']:.2f}x is below break-even {BREAK_EVEN:.2f}x")
        if m["health"][0] == "g" and a7["roas"] is not None and a30["roas"] is not None and a7["roas"] >= a30["roas"] and a7["profit"] > 0:
            return ("up", "Spend more", f"7-day ROAS {a7['roas']:.2f}x is at or above 30-day {a30['roas']:.2f}x")
        return ("hold", "Hold", "Not clearly better or worse")

    def rag(r):
        return "n" if r is None else ("g" if r >= BREAK_EVEN * 1.2 else ("y" if r >= BREAK_EVEN else "r"))

    def flag_for(m):
        if m["act"]:
            rk = m.get("rank"); r30 = m["h30"][0]; r7 = m["h7"][0]
            if m["30"]["spend"] >= MINSP and m["health"][0] in ("r", "y") and (r7 is None or r7 < BREAK_EVEN * 1.2) and rk and rk["n"] >= 2 and rk["rank"] > rk["n"] / 2:
                return ("close", "Close", f"30-day ROAS {('%.2fx' % r30) if r30 is not None else 'n/a'} vs break-even {BREAK_EVEN:.2f}x, ranked #{rk['rank']} of {rk['n']}")
            return None
        rl = m["lh"][0]; lrr = m["lr"][0]
        if m["nspend"] >= 5 and m["life"]["spend"] >= 50 and rl is not None:
            lrt = f"{lrr:.2f}x" if lrr is not None else "too little spend"
            if rl >= BREAK_EVEN * 1.2:
                return ("reopen", "Reopen", f"Lifetime ROAS {rl:.2f}x over {m['nspend']} spend days (last run {lrt}). A weak last run may be seasonal.")
            if rl < BREAK_EVEN:
                return ("keep", "Keep closed", f"Lifetime ROAS {rl:.2f}x is below break-even {BREAK_EVEN:.2f}x (last run {lrt}).")
        return None

    def finalize(ents):
        cl = [x for x in ents if x.get("flag") and x["flag"][0] == "close"]
        cl.sort(key=lambda x: (-x["rank"]["rank"], -x["30"]["spend"]))
        for k, x in enumerate(cl, 1):
            x["flag"] = ("close", f"Close #{k}", x["flag"][2] + f". Worst first, {k} of {len(cl)}.")
        ro = [x for x in ents if x.get("flag") and x["flag"][0] == "reopen"]
        if ro:
            ids = list(range(len(ro)))
            a = pctl({i: ro[i]["life"]["profit"] for i in ids}, True); b = pctl({i: (ro[i]["life"]["roas"] or 0) for i in ids}, True)
            sc = {i: 0.7 * a[i] + 0.3 * b[i] for i in ids}
            for k, i in enumerate(sorted(ids, key=lambda i: -sc[i]), 1):
                ro[i]["flag"] = ("reopen", f"Reopen #{k}", ro[i]["flag"][2] + f" Best first, {k} of {len(ro)}.")
                ro[i]["rr"] = dict(k=k, n=len(ro))

    # ad groups (daily, Google basis)
    agd = defaultdict(lambda: defaultdict(dict))
    for r in raw.get("adgroups_daily") or []:
        cid = str(r.get("campaign_id"))
        if cid not in camps or not r.get("ad_group_name"):
            continue
        try:
            d = D.fromisoformat(str(r.get("date"))[:10])
        except ValueError:
            continue
        x = agd[cid][str(r["ad_group_name"])].setdefault(d, dict(spend=0.0, rev=0.0, gval=0.0, conv=0.0, clicks=0.0, impr=0.0, orders=0))
        x["spend"] += z(r.get("spend")); x["gval"] += z(r.get("conversions_value")); x["conv"] += z(r.get("conversions"))
        x["clicks"] += z(r.get("clicks")); x["impr"] += z(r.get("impressions"))
    ag_ok = bool(raw.get("adgroups_daily")) if "adgroups_daily" in raw else None

    table = []
    for cid, c in camps.items():
        days_ = ent_days(cid)
        act = (c["status"] or "") == "ENABLED"
        m = emetrics(days_, act, "owner")
        m.update(id=cid, name=c["name"], short=short_name(c["name"]), type=c["type"], status=c["status"], budget=c["budget"], launched=(c["first"].isoformat() if c["first"] else None))
        w30 = m["30"]; gap = None
        if w30["spend"] >= MINSP and w30["groas"] is not None and w30["groas"] >= BREAK_EVEN and (w30["roas"] or 0) < BREAK_EVEN and \
           max(w30["rev"], w30["gval"]) > 0 and min(w30["rev"], w30["gval"]) / max(w30["rev"], w30["gval"]) < 0.5:
            gap = f"Tracking gap: Google shows {w30['groas']:.2f}x, Shopify matches {w30['rev'] / w30['gval'] * 100:.0f}% of its value"
        m["gap"] = gap
        m["kids"] = []
        for gname, gd in agd.get(cid, {}).items():
            gm = emetrics(gd, act and any(x["spend"] > 0 and d >= yday - dt.timedelta(days=14) for d, x in gd.items()), "google")
            gm.update(name=gname)
            m["kids"].append(gm)
        rk = rank_group({i: x for i, x in enumerate(m["kids"]) if x["act"]})
        for i, x in enumerate(m["kids"]):
            x["rank"] = rk.get(i); x["sig"] = sig_for(x); x["flag"] = flag_for(x)
        finalize(m["kids"])
        m["kids"] = [x for x in m["kids"] if x["30"]["spend"] > 0 or (x["flag"] and x["flag"][0] == "reopen")]
        m["kids"].sort(key=lambda x: (not x["act"], -x["30"]["spend"], -x["life"]["spend"]))
        table.append(m)
    rkc = rank_group({i: x for i, x in enumerate(table) if x["act"]})
    for i, x in enumerate(table):
        x["rank"] = rkc.get(i); x["sig"] = sig_for(x, x["gap"]); x["flag"] = flag_for(x)
    finalize(table)
    table.sort(key=lambda x: (not x["act"], -x["30"]["spend"], -x["life"]["spend"]))
    table = [x for x in table if x["life"]["spend"] > 0 or x["life"]["rev"] > 0]
    un_days = {d: dict(spend=0.0, rev=r, gval=0.0, conv=0.0, clicks=0.0, impr=0.0, orders=oord[""].get(d, 0)) for d, r in orev[""].items()}
    unattr = emetrics(un_days, True, "owner")
    total_days = {}
    for t_ in table:
        pass
    fam_days = defaultdict(lambda: dict(spend=0.0, rev=0.0, gval=0.0, conv=0.0, clicks=0.0, impr=0.0, orders=0))
    for cid in camps:
        for d, x in ent_days(cid).items():
            for k in x:
                fam_days[d][k] += x[k]
    for d, x in un_days.items():
        for k in x:
            fam_days[d][k] += x[k]
    famm = emetrics(dict(fam_days), True, "owner")

    # impression share windows (impression-weighted) with previous-period change (percentage points)
    def share(a, b):
        rows_ = [(v, cid) for cid, dd in cday.items() for d, v in dd.items() if a <= d <= b]
        out = {}
        for key in ("is_", "lb", "lr"):
            vals = [(v[key], v["impr"]) for v, _ in rows_ if v[key] is not None and v["impr"] > 0]
            w_ = sum(i for _, i in vals)
            out[key] = (sum(x * i for x, i in vals) / w_) if w_ > 0 else None
        return out
    vis = dict(cur=share(*W["30"]), prev=share(*PREV["30"]), cur7=share(*W["7"]), prev7=share(*PREV["7"]))
    vis["by_camp"] = {}
    for cid in camps:
        dd = cday[cid]
        def sh(a, b, key):
            vals = [(v[key], v["impr"]) for d, v in dd.items() if a <= d <= b and v[key] is not None and v["impr"] > 0]
            w_ = sum(i for _, i in vals)
            return (sum(x * i for x, i in vals) / w_) if w_ > 0 else None
        vis["by_camp"][cid] = {k: dict(cur=sh(*W["30"], k), prev=sh(*PREV["30"], k)) for k in ("is_", "lb", "lr")}

    return dict(
        generated=now.isoformat(), tz="Australia/Melbourne", today=today.isoformat(), yesterday=yday.isoformat(),
        data_through=dict(google=last_g.isoformat(), shopify=last_order.isoformat(), completed=yday.isoformat()),
        fetch_status=status, constants=dict(contrib=CONTRIB, break_even=BREAK_EVEN, gst=1 / 11, product_cost=0.25),
        life_start=life_start.isoformat(), first_spend=first_spend.isoformat(), first_order=first_order.isoformat(),
        periods=periods, prev=prev, confidence=dict(level=conf, why=conf_why), signal=signal, mtd=mtd, mtd_label=mtd_label,
        velocity=velocity, campaigns=camp_rows, camp_meta={cid: dict(name=c["name"], short=short_name(c["name"]), type=c["type"], status=c["status"]) for cid, c in camps.items()},
        drill=drill, waste=waste, waste_total=waste_total, waste_win=waste_win, orders=order_table, unresolved_utms=dict(unresolved_utms),
        attribution=attribution, months=months, days=days, cum=cum, today_block=today_block, waiting=waiting, issues=issues, actions=actions, recon=recon, trk=trk, gmatch=gmatch, gsum=gsum, gm_ok=bool(raw.get("conversions_daily")), pace=pace_rows, table=table, unattr=unattr, family=famm, vis=vis, ag_ok=ag_ok,
    )


# --------------------------------------------------------------------------------------
# 2. VALIDATE
# --------------------------------------------------------------------------------------
def validate(p):
    bad = []

    def finite(path, v):
        if isinstance(v, float) and not math.isfinite(v):
            bad.append("non-finite number at " + path)
        elif isinstance(v, dict):
            for k, x in v.items():
                finite(path + "." + str(k), x)
        elif isinstance(v, list):
            for i, x in enumerate(v[:2000]):
                finite(path + f"[{i}]", x)
    finite("payload", p)
    try:
        y, t = D.fromisoformat(p["yesterday"]), D.fromisoformat(p["today"])
        if y != t - dt.timedelta(days=1):
            bad.append("yesterday is not the day before today")
        if p["periods"]["yesterday"]["to"] != p["yesterday"] or p["periods"]["7"]["to"] != p["yesterday"]:
            bad.append("completed windows must end on yesterday")
        if (D.fromisoformat(p["periods"]["7"]["to"]) - D.fromisoformat(p["periods"]["7"]["from"])).days != 6:
            bad.append("7-day window is not 7 days")
        if (D.fromisoformat(p["periods"]["30"]["to"]) - D.fromisoformat(p["periods"]["30"]["from"])).days != 29:
            bad.append("30-day window is not 30 days")
        if D.fromisoformat(p["data_through"]["google"]) < y - dt.timedelta(days=3):
            bad.append("Google data is more than 3 days behind yesterday")
    except Exception as e:
        bad.append("date logic: " + str(e))
    a = p["attribution"]
    if a["with_campaign"] + a["unattributed"] != a["total"]:
        bad.append("campaign-attributed + unattributed != total matched")
    if a["exact"] + a["strong"] + a["probable"] != a["total"]:
        bad.append("tier counts do not add up to total matched")
    for k_, x_ in (p.get("gsum") or {}).items():
        if x_["n_ct"] + x_["n_cn"] + x_["n_mu"] + x_["n_mx"] + x_["n_none"] != x_["n"] or abs(x_["v_ct"] + x_["v_cn"] + x_["v_mu"] + x_["v_mx"] + x_["v_none"] - x_["val"]) > 0.01:
            bad.append(f"Google conversion matching does not add up ({k_})")
    for k, r in p["periods"].items():
        if r["camp_orders"] + r["un_orders"] != r["orders"]:
            bad.append(f"{k}: reconciliation orders do not add up")
        if abs(r["camp_rev"] + r["un_rev"] - r["rev"]) > 0.01:
            bad.append(f"{k}: reconciliation revenue does not add up")
        if r["spend"] < -0.001 or r["rev"] < -0.001:
            bad.append(f"{k}: negative spend or revenue")
        exp = r["rev"] * CONTRIB - r["spend"] - r.get("fee", 0.0)
        if abs(exp - r["profit"]) > 0.01:
            bad.append(f"{k}: profit does not follow the formula")
    # campaign rows must sum to the family total (spend) for every window
    for k, rows in p["campaigns"].items():
        s = sum(r["spend"] for r in rows)
        if abs(s - p["periods"][k]["spend"]) > 0.05:
            bad.append(f"{k}: campaign spend ({s:.2f}) != family spend ({p['periods'][k]['spend']:.2f})")
        rv = sum(r["rev"] for r in rows)
        if rv - p["periods"][k]["rev"] > 0.01:
            bad.append(f"{k}: campaign revenue exceeds family revenue")
    if len(p["days"]) and abs(sum(d["spend"] for d in p["days"]) - p["periods"]["life"]["spend"]) > 0.05:
        bad.append("daily spend does not sum to lifetime spend")
    return bad


# --------------------------------------------------------------------------------------
# 3. RENDER
# --------------------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s))


def money(v, dp=0, plus=False):
    if v is None:
        return "—"
    s = "{:,.{}f}".format(abs(v), dp)
    return ("−" if v < -0.0000001 and float(s.replace(",", "")) != 0 else ("+" if plus and v > 0 else "")) + "$" + s


def pct(v, dp=1):
    return "—" if v is None else f"{v * 100:.{dp}f}%"


def rx(v):
    return "—" if v is None else f"{v:.2f}x"


def n0(v):
    return "—" if v is None else f"{v:,.0f}"


def n1(v):
    return "—" if v is None else f"{v:,.1f}"


def cls(v):
    return "pos" if (v or 0) > 0.005 else ("neg" if (v or 0) < -0.005 else "")


def svg_line(vals, w=640, h=150, label_fmt=money):
    if not vals:
        return ""
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    if hi == lo:
        hi = lo + 1
    pad = 6
    xs = lambda i: pad + (w - 2 * pad) * (i / max(1, len(vals) - 1))
    ys = lambda v: h - pad - (h - 2 * pad) * ((v - lo) / (hi - lo))
    pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(vals))
    zero = ys(0)
    col = "var(--good)" if vals[-1] >= 0 else "var(--bad)"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="chart" role="img" aria-label="Cumulative profit">'
            f'<line x1="0" x2="{w}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="var(--line)" stroke-dasharray="4 4"/>'
            f'<polyline fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="round" points="{pts}"/></svg>')


def svg_bars(vals, w=640, h=120, signed=True):
    if not vals:
        return ""
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    if hi == lo:
        hi = lo + 1
    n = len(vals)
    bw = (w - 8) / n
    zero = h - 4 - (h - 8) * ((0 - lo) / (hi - lo))
    out = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="chart" role="img" aria-label="Daily profit"><line x1="0" x2="{w}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="var(--line)"/>']
    for i, v in enumerate(vals):
        y = h - 4 - (h - 8) * ((v - lo) / (hi - lo))
        top, ht = (y, zero - y) if v >= 0 else (zero, y - zero)
        out.append(f'<rect x="{4 + i * bw + 1:.1f}" y="{top:.1f}" width="{max(1.0, bw - 2):.1f}" height="{max(0.8, ht):.1f}" fill="{"var(--good)" if v >= 0 else "var(--bad)"}" rx="1.5"/>')
    out.append("</svg>")
    return "".join(out)


def svg_pairs(a, b, w=640, h=120):
    """spend (grey) vs matched revenue (green) side by side."""
    n = len(a)
    if not n:
        return ""
    hi = max(max(a), max(b), 1)
    bw = (w - 8) / n
    out = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="chart" role="img" aria-label="Spend vs matched revenue">']
    for i in range(n):
        for j, (v, c) in enumerate(((a[i], "var(--grey)"), (b[i], "var(--good)"))):
            ht = (h - 6) * v / hi
            out.append(f'<rect x="{4 + i * bw + j * (bw - 2) / 2 + 1:.1f}" y="{h - 3 - ht:.1f}" width="{max(1.0, (bw - 3) / 2):.1f}" height="{max(0.6, ht):.1f}" fill="{c}" rx="1"/>')
    out.append("</svg>")
    return "".join(out)


SIGCLS = {"SCALE": "g", "HOLD": "a", "WATCH": "gr", "REDUCE": "r", "FIX TRACKING": "r"}
TIERCLS = {"Exact": "g", "Strong": "g", "Probable": "a", "Unmatched": "gr"}


CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_tracked.css")
JS_THEME = """<script>
(function(){var r=document.documentElement,b=document.getElementById('tg');
function cur(){var t=r.getAttribute('data-theme');if(t)return t;return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
function lab(){b.textContent=cur()==='dark'?'Light mode':'Dark mode'}
try{var s=localStorage.getItem('gt-theme');if(s)r.setAttribute('data-theme',s)}catch(e){}
lab();b.addEventListener('click',function(){var n=cur()==='dark'?'light':'dark';r.setAttribute('data-theme',n);try{localStorage.setItem('gt-theme',n)}catch(e){}lab()});})();
document.addEventListener('click',function(e){var b=e.target.closest('.chip');if(!b)return;var g=b.dataset.g,w=b.dataset.w;var p=b.parentNode;p.querySelectorAll('.chip').forEach(function(x){x.classList.toggle('on',x===b)});document.querySelectorAll('[data-grp="'+g+'"]').forEach(function(x){x.hidden=x.dataset.w!==w})});
</script>
<script>
(function(){var rows=document.querySelectorAll('tr.cp');var xa=document.getElementById('xa');
function set(tr,o){tr.classList.toggle('open',o);var b=tr.querySelector('.xp');if(b)b.setAttribute('aria-expanded',o);
document.querySelectorAll('tr.as[data-p="'+tr.getAttribute('data-id')+'"]').forEach(function(a){a.hidden=!o})}
rows.forEach(function(tr){if(!tr.querySelector('.xp'))return;tr.addEventListener('click',function(){set(tr,!tr.classList.contains('open'))})});
if(xa)xa.addEventListener('click',function(){var open=xa.getAttribute('data-o')!=='1';rows.forEach(function(tr){if(tr.querySelector('.xp'))set(tr,open)});xa.setAttribute('data-o',open?'1':'0');xa.textContent=open?'Collapse all ad groups':'Expand all ad groups'});})();
</script>
<script>
(function(){var _r=document.querySelector('tr.cp'),wrap=_r?_r.closest('.wrap'):null,bar=document.querySelector('.jump');if(!wrap||!bar)return;var box=wrap.parentNode;
var heads=[].slice.call(wrap.querySelectorAll('thead th.gh, thead th.hh'));
function stk(){var r=wrap.querySelectorAll('thead tr');if(r.length>1){var jh=bar.getBoundingClientRect().height,h=r[0].getBoundingClientRect().height;wrap.style.setProperty('--jh',jh+'px');r[1].querySelectorAll('th').forEach(function(t){t.style.top=(jh+h)+'px'});wrap.style.setProperty('--hh',(jh+h+r[1].getBoundingClientRect().height)+'px')}}stk();window.addEventListener('resize',stk);window.addEventListener('load',stk);if(window.ResizeObserver)new ResizeObserver(stk).observe(wrap.querySelector('thead'));
function sw(){var h=wrap.querySelector('thead th.hcamp');return h?h.getBoundingClientRect().width:0}
function left(el){return el.getBoundingClientRect().left-wrap.getBoundingClientRect().left+wrap.scrollLeft}
function go(i){var el=heads[i];if(!el)return;wrap.scrollTo({left:Math.max(0,left(el)-sw()-2),behavior:'smooth'})}
var btns=[].slice.call(bar.querySelectorAll('button[data-i]'));
function cur(){var sl=wrap.scrollLeft+sw(),best=0,bd=1e9;heads.forEach(function(h,i){var d=Math.abs(left(h)-sl);if(d<bd){bd=d;best=i}});return best}
function upd(){var c=cur();btns.forEach(function(b){b.classList.toggle('on',+b.getAttribute('data-i')===c)});box.classList.toggle('mr',wrap.scrollLeft+wrap.clientWidth<wrap.scrollWidth-4)}
function lift(){var t=wrap.getBoundingClientRect().top;if(t>8||t<-8)window.scrollBy({top:t-4,behavior:'smooth'})}
btns.forEach(function(b){b.addEventListener('click',function(){lift();go(+b.getAttribute('data-i'))})});
bar.querySelectorAll('button[data-step]').forEach(function(b){b.addEventListener('click',function(){go(Math.min(heads.length-1,Math.max(0,cur()+(+b.getAttribute('data-step')))))})});
wrap.addEventListener('scroll',upd,{passive:true});window.addEventListener('resize',upd);upd();
var tb=document.createElement('button');tb.id='totop';tb.type='button';tb.setAttribute('aria-label','Back to top');tb.textContent='\\u2191';document.body.appendChild(tb);
function tt(){tb.classList.toggle('on',window.scrollY>400||wrap.scrollTop>120)}
tb.addEventListener('click',function(){wrap.scrollTop=0;window.scrollTo({top:0,behavior:'smooth'})});
window.addEventListener('scroll',tt,{passive:true});wrap.addEventListener('scroll',tt,{passive:true});tt();})();
</script>"""

PERIODS = [("yesterday", "t", "Yesterday"), ("7", "w", "Last 7 days"), ("15", "x", "Last 15 days"), ("30", "m", "Last 30 days"), ("life", "l", "Lifetime")]


def fm(v, dp=None):
    if v is None:
        return "—"
    if dp is None:
        dp = 0 if abs(v) >= 1000 else 2
    s = f"{abs(v):,.{dp}f}"
    return ("−" if v < 0 and float(s.replace(",", "")) != 0 else "") + "$" + s


def arrow(now, prev, hg):
    if now is None or prev is None or abs(now - prev) < 1e-9:
        return ""
    up = now > prev
    c = "nt" if hg is None else ("gd" if up == hg else "bd")
    return f'<i class="ar {c}" title="{"Up" if up else "Down"} vs previous period">{"▲" if up else "▼"}</i>'


def chg(now, prev, hg=True):
    if now is None or prev is None or abs(prev) < 1e-9:
        return '<span class="chg nt">no prior baseline</span>'
    pc = (now - prev) / abs(prev)
    up = pc > 0
    c = "nt" if (abs(pc) < 0.005 or hg is None) else ("gd" if up == hg else "bd")
    txt = ">999%" if abs(pc) > 9.99 else f"{abs(pc) * 100:.0f}%"
    return f'<span class="chg {c}">{"▲" if up else "▼"} {txt}</span>'


def rcls(r):
    return "none" if r is None else ("g" if r >= BREAK_EVEN * 1.2 else ("y" if r >= BREAK_EVEN else "r"))


def front_numbers(p):
    """Yesterday (set at the 6 am refresh), or today so far once the 8 pm refresh has run. Used by the report card and the hub tile."""
    P = p["periods"]; tb = p["today_block"]; WT = p["waiting"]
    gen = dt.datetime.fromisoformat(p["generated"]); yd = D.fromisoformat(p["yesterday"])
    if gen.hour >= 20 and tb["has_google"]:
        d = dict(label="Today", day="today", sub=gen.strftime("%a %-d %b") + ", as of " + gen.strftime("%-I:%M %p") + " refresh", spend=tb["spend"], rev=tb["rev"],
                 gval=tb["gval"] or 0, conv=tb["conv"] or 0, orders=tb["orders"], wait=WT["today"])
    else:
        r_ = P["yesterday"]
        d = dict(label="Yesterday", day="yesterday", sub=yd.strftime("%a %-d %b") + ", complete day", spend=r_["spend"], rev=r_["rev"], gval=r_["gval"], conv=r_["conv"], orders=r_["orders"], wait=WT["yesterday"])
    d["profit"] = d["rev"] * CONTRIB - d["spend"] - FEE_DAY
    d["att"] = (min(d["rev"], d["gval"]) / max(d["rev"], d["gval"])) if (d["rev"] and d["gval"]) else None
    return d


def render(p):
    P = p["periods"]; PV = p["prev"]
    yd = D.fromisoformat(p["yesterday"]); gen = dt.datetime.fromisoformat(p["generated"])
    sig = p["signal"]; conf = p["confidence"]; st = p["fetch_status"]
    BE = BREAK_EVEN
    css = open(CSS_PATH).read()
    esc_ = esc
    rng_ = lambda k: f'{D.fromisoformat(P[k]["from"]).strftime("%-d %b")}' + ("" if P[k]["from"] == P[k]["to"] else f' to {D.fromisoformat(P[k]["to"]).strftime("%-d %b %Y")}')

    # ---------- KPI cards
    def kpi(k, cls_, label, note):
        r = P[k]; pr = PV.get(k)
        def cell(lbl, val, key, hg, fmt):
            return f'<div><b>{fmt(val)}</b>{chg(val, pr[key], hg) if pr else ""}<span>{lbl}</span></div>'
        return (f'<div class="kpi {cls_}"><h2>{label}</h2><p class="rg">{rng_(k)}</p><div class="kv k4">'
                + cell("spend", r["spend"], "spend", None, lambda v: fm(v))
                + cell("revenue", r["rev"], "rev", True, lambda v: fm(v))
                + cell("ROAS", r["roas"], "roas", True, rx)
                + cell("profit", r["profit"], "profit", True, lambda v: fm(v))
                + f'</div><p class="gs">Google reports {fm(r["gval"])} · {rx(r["groas"])} · {n1(r["conv"])} conversions. Shopify matched {r["orders"]} orders. Profit includes {fm(r["fee"])} expert fee.</p><p class="kn">{note}</p></div>')
    pnote = lambda k: "Arrows compare with the " + ("day before, " if k == "yesterday" else f"{(D.fromisoformat(PV[k]['to']) - D.fromisoformat(PV[k]['from'])).days + 1} days before, ") + (D.fromisoformat(PV[k]["from"]).strftime("%a %-d %b") if k == "yesterday" else D.fromisoformat(PV[k]["from"]).strftime("%-d %b") + " to " + D.fromisoformat(PV[k]["to"]).strftime("%-d %b")) + "."
    def front_card():
        fn = front_numbers(p); WT = p["waiting"]
        label, sub, spend, rev, gval, conv, n_o, wait, profit, att = fn["label"], fn["sub"], fn["spend"], fn["rev"], fn["gval"], fn["conv"], fn["orders"], fn["wait"], fn["profit"], fn["att"]
        ac = "none" if att is None else ("g" if att >= .8 else ("y" if att >= .5 else "r"))
        pc = "g" if profit > 0 else "r"
        wn = wait["n"]
        flag = (f'<span class="p y">{wn} order{"s" if wn != 1 else ""} waiting for attribution</span>' if wn else '<span class="p g">No orders waiting for attribution</span>')
        return (f'<div class="kpi kt"><h2>{label}</h2><p class="rg">{sub}</p><div class="kv k4">'
                f'<div><b>{fm(spend)}</b><span>spend</span></div><div><b>{fm(rev)}</b><span>revenue</span></div>'
                f'<div><b><span class="p {pc}" style="color:inherit">{fm(profit)}</span></b><span>profit</span></div>'
                f'<div><b><span class="p {ac}">{(format(att * 100, ".0f") + "%") if att is not None else "—"}</span></b><span>attribution</span></div></div>'
                f'<p class="gs">Google reports {fm(gval)} · {n1(conv)} conversions. Shopify matched {n_o} orders. Profit includes {fm(FEE_DAY)} expert fee.</p>'
                f'<p class="kn">{flag} For reference: see the order attribution report.</p></div>')
    kpis = ('<section class="kpis">' + front_card() + kpi("7", "kw", "Last 7 days", pnote("7")) + kpi("30", "km", "Last 30 days", pnote("30"))
            + kpi("life", "kl", "Lifetime", f'Since {D.fromisoformat(p["life_start"]).strftime("%-d %b %Y")}, the first day with both tracked spend and Shopify order history.') + '</section>')

    # ---------- budget signal block
    scls = {"SCALE": "scale", "HOLD": "hold", "WATCH": "hold", "REDUCE": "cut", "FIX TRACKING": "cut"}[sig["code"]]
    mtd = p["mtd"]; v = p["velocity"]
    why = "".join(f"<li>{esc(x)}</li>" for x in sig["reasons"])
    iss = "".join(f'<li class="iss {i["sev"]}"><b>{esc(i["what"])}</b><span><i>Why it matters:</i> {esc(i["why"])}</span><span><i>Action:</i> {esc(i["action"])}</span></li>' for i in p["issues"])
    acts = "".join(f'<li class="iss {a["sev"]}"><b>{esc(a["action"])}</b><span>{esc(a["why"])}</span></li>' for a in p["actions"]) or "<li>No action needed.</li>"
    _r7 = P["7"]["roas"]; _vd = v["d7"]
    _rc = "r" if (_r7 is None or _r7 < BE) else ("g" if _r7 >= BE * 1.2 else "y")
    _cc = {"High": "g", "Medium": "y", "Low": "r"}.get(conf["level"], "y")
    _mc = "none" if not mtd else ("g" if mtd["profit"] > 0 else "r")
    _vc = "g" if _vd > 0 else ("r" if _vd < 0 else "none")
    _tile = lambda c, lab, val: f'<div class="stt {c}"><span>{lab}</span><b>{val}</b></div>'
    sgtiles = (_tile(_mc, "Profit this month", fm(mtd["profit"]) if mtd else "—") + _tile(_vc, "Profit per day (7d)", fm(_vd, 0))
               + _tile(_rc, "ROAS (7d)", rx(_r7)) + _tile("none", "Break-even ROAS", f"{BE:.2f}x") + _tile(_cc, "Tracking confidence", esc(conf["level"])))
    sigp = f'''<section class="sig {scls}"><div class="sg"><span class="sgl">Budget signal</span><b>{esc(sig["code"].title() if sig["code"] != "FIX TRACKING" else "Fix tracking")}</b><p>{esc(sig["headline"])}</p></div>
<div class="sgm five sgt">{sgtiles}</div>
<p class="sgn">Profit = revenue ÷ 1.1 × 0.75 − ad spend − $155/week expert fee. Completed days only, through {yd.strftime("%a %-d %b")}.</p>
<details class="sgn why"><summary>Why this signal</summary><ul>{why}</ul></details>
<details class="sgn why"><summary>Issues ({len([i for i in p["issues"] if "No issues" not in i["what"]])})</summary><ul class="il" style="list-style:none;padding:0">{iss}</ul></details>
<details class="sgn why"><summary>Actions ({len(p["actions"])})</summary><ul class="il" style="list-style:none;padding:0">{acts}</ul></details></section>'''

    # ---------- status strip
    a = p["attribution"]; opt_fail = [k for k, x in st.items() if not x.get("ok")]
    p30 = P["30"]
    cdot = {"High": "g", "Medium": "y", "Low": "r"}.get(conf["level"], "")
    gd = D.fromisoformat(p["data_through"]["google"]); sd = D.fromisoformat(p["data_through"]["shopify"])
    gcls = "g" if st.get("campaigns", {}).get("ok") and gd >= yd else ("y" if st.get("campaigns", {}).get("ok") else "r")
    scls = "g" if st.get("orders", {}).get("ok") and sd >= yd else ("y" if st.get("orders", {}).get("ok") else "r")
    mcls = {"High": "g", "Medium": "y", "Low": "r"}.get(conf["level"], "y")
    mval = (format(p30["match_rev"] * 100, ".0f") + "%") if p30["match_rev"] is not None else esc(conf["level"])
    strip = f'''<section class="sttw">
<div class="stt {gcls}"><span>Google Ads data up to</span><b>{gd.strftime("%-d %b")}</b></div>
<div class="stt {scls}"><span>Shopify orders up to</span><b>{sd.strftime("%-d %b")}</b></div>
<div class="stt {mcls}"><span>Google sales seen in Shopify</span><b>{mval}</b></div>
<div class="stt {"g" if not opt_fail else "y"}"><span>Report refreshed</span><b>{gen.strftime("%-I:%M %p")}</b></div></section>'''

    # ---------- pace + chart + visibility
    prow = "".join(f'<tr><th scope="row">{esc(r["label"])}</th><td><span class="p {"g" if r["profit"] > .005 else ("r" if r["profit"] < -.005 else "none")}">{fm(r["profit"])}</span></td><td><span class="p {"g" if r["per_day"] > .005 else ("r" if r["per_day"] < -.005 else "none")}">{fm(r["per_day"], 2)}/day</span></td><td>{("—" if r["change"] is None else f"""<span class="p {"g" if r["change"] > 0 else "r"}">{"▲" if r["change"] > 0 else "▼"} {abs(r["change"]) * 100:.0f}%</span>""")}</td></tr>' for r in p["pace"])
    pace = f'<div class="box"><h2>Profit pace</h2><p class="sub">Average profit per day and change versus the period before.</p><div class="tw"><table class="mini"><thead><tr><th></th><th>Profit</th><th>Per day</th><th>Change</th></tr></thead><tbody>{prow}</tbody></table></div></div>'
    days = p["days"]
    def chart(n, w=900, h=300, fs=12):
        xs = days[-n:] if n else days
        vals = [x["profit"] for x in xs]; cum = []; r_ = 0.0
        for x in xs:
            r_ += x["profit"]; cum.append(r_)
        lo, hi = min(min(vals + cum), 0), max(max(vals + cum), 0)
        if hi == lo: hi = lo + 1
        L, R, T, B = (52 if w > 600 else 46), 10, 26, 28
        Y = lambda t: T + (h - T - B) * (1 - (t - lo) / (hi - lo))
        bw = (w - L - R) / len(xs)
        out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Daily and cumulative profit">']
        step = (hi - lo) / 4
        for g in range(5):
            gv = lo + step * g
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="var(--line)" stroke-width="1"/><text x="{L - 5}" y="{Y(gv) + 3.5:.1f}" text-anchor="end" font-size="{fs}" fill="var(--muted)">{fm(gv, 0)}</text>')
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--muted)" stroke-width="1.2"/>')
        for i, vv in enumerate(vals):
            t, b = (Y(vv), Y(0)) if vv >= 0 else (Y(0), Y(vv))
            out.append(f'<rect x="{L + i * bw + 1:.1f}" y="{t:.1f}" width="{max(1.0, bw - 2):.1f}" height="{max(.8, b - t):.1f}" rx="1.5" fill="{"var(--g)" if vv >= 0 else "var(--r)"}" opacity=".85"><title>{xs[i]["date"]}: {fm(vv, 2)}</title></rect>')
        pts = " ".join(f"{L + (i + .5) * bw:.1f},{Y(c):.1f}" for i, c in enumerate(cum))
        out.append(f'<polyline fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round" points="{pts}"/>')
        every = max(1, round(len(xs) / (6 if w > 600 else 4)))
        for i in range(0, len(xs), every):
            out.append(f'<text x="{L + (i + .5) * bw:.1f}" y="{h - 8}" text-anchor="middle" font-size="{fs}" fill="var(--muted)">{D.fromisoformat(xs[i]["date"]).strftime("%-d %b")}</text>')
        # data labels on every bar when the window is short enough to read, otherwise best / worst / latest only
        lf = max(8, fs - 3)
        lab_all = len(xs) <= 31
        skip = 1 if (w > 600 or len(xs) <= 15) else 2
        marks = {}
        if vals:
            bi = max(range(len(vals)), key=lambda i: vals[i]); wi = min(range(len(vals)), key=lambda i: vals[i])
            for i in ([j for j in range(len(vals)) if (j % skip == 0 or j in (bi, wi, len(vals) - 1))] if lab_all else sorted({bi, wi, len(vals) - 1})):
                marks[i] = vals[i]
        for i, vv in marks.items():
            x = L + (i + .5) * bw
            y = Y(vv) - 4 if vv >= 0 else Y(vv) + lf + 2
            col = "var(--g)" if vv >= 0 else "var(--r)"
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="{lf}" font-weight="700" fill="{col}">{fm(vv, 0)}</text>')
        out.append(f'<circle cx="{L + (len(xs) - .5) * bw:.1f}" cy="{Y(cum[-1]):.1f}" r="3.5" fill="var(--ink)"/><text x="{w - R}" y="{Y(cum[-1]) - 8:.1f}" text-anchor="end" font-size="{fs}" font-weight="700" fill="var(--ink)">Total {fm(cum[-1], 0)}</text></svg>')
        return "".join(out)
    TW = [("yesterday", "Yesterday", 7), ("7", "7 days", 7), ("15", "15 days", 15), ("30", "30 days", 30), ("life", "Lifetime", 0)]
    def ttiles(k):
        r = P[k]; pr = PV.get(k)
        def t_(l, v, key, hg, fmt, tone=""):
            return f'<div class="tl {tone}"><span>{l}</span><b>{fmt(v)}</b>{chg(v, pr[key], hg) if pr else ""}</div>'
        pc = "g" if r["profit"] > .005 else ("r" if r["profit"] < -.005 else "")
        rc = {"g": "g", "y": "y", "r": "r"}.get(rcls(r["roas"]), "") if r["roas"] is not None else ""
        return f'<div class="tls">' + t_("Spend", r["spend"], "spend", None, lambda v: fm(v)) + t_("Revenue", r["rev"], "rev", True, lambda v: fm(v)) + t_("ROAS", r["roas"], "roas", True, rx, rc) + t_("Profit", r["profit"], "profit", True, lambda v: fm(v), pc) + "</div>"
    def trange(k):
        r = P[k]; a_, b_ = D.fromisoformat(r["from"]), D.fromisoformat(r["to"])
        return a_.strftime("%a %-d %b") if a_ == b_ else f'{a_.strftime("%-d %b")} to {b_.strftime("%-d %b %Y")}'
    chart_box = (f'<div class="box"><h2>Profit trend</h2><p class="sub">Pick a period for the totals. The chart shows each day (last 7 days minimum): bar = that day\'s profit, line = running total.</p><div style="margin-bottom:10px">'
                 + "".join(f'<button type="button" class="chip{" on" if k == "30" else ""}" data-g="tr" data-w="{k}">{l}</button>' for k, l, _ in TW) + '</div>'
                 + "".join(f'<div data-grp="tr" data-w="{k}"{"" if k == "30" else " hidden"}><p class="rg" style="margin:0 0 6px">{trange(k)}</p>{ttiles(k)}<div class="cw">{chart(n)}</div><div class="cmb">{chart(n, 420, 320, 12)}</div></div>' for k, _, n in TW)
                 + '<p class="legend"><span><i class="dot g"></i>Green bar: a profitable day</span><span><i class="dot r"></i>Red bar: a losing day</span><span><b>Black line</b>: running total. Rising means profit is building, falling means losses.</span></p></div>')
    vis = p["vis"]; vc, vp = vis["cur"], vis["prev"]
    n_budget = sum(1 for c in p["table"] if c["act"] and (vis["by_camp"].get(c["id"], {}).get("lb", {}).get("cur") or 0) >= .10)
    def pp(cur, prev, hg):
        if cur is None or prev is None: return "—"
        d = (cur - prev) * 100
        if abs(d) < .05: return '<span class="chg nt">0.0 pp</span>'
        return f'<span class="p {"g" if (d > 0) == hg else "r"}">{"▲" if d > 0 else "▼"} {abs(d):.1f} pp</span>'
    def vrow(label, key, hg, reason, sugg):
        cur = vc[key]
        col = {"is_": ("g" if (cur or 0) >= .6 else ("y" if (cur or 0) >= .4 else "r")), "lb": ("g" if (cur or 0) < .05 else ("y" if (cur or 0) < .15 else "r")), "lr": ("g" if (cur or 0) < .2 else ("y" if (cur or 0) < .4 else "r"))}[key]
        return f'<tr><th scope="row">{label}<small>{esc(reason)}</small></th><td><span class="p {col}">{pct(cur, 1)}</span></td><td>{pp(cur, vp[key], hg)}</td><td>{sugg}</td></tr>'
    is_c, lb_c, lr_c = vc["is_"], vc["lb"], vc["lr"]
    vis_rows = ""
    if is_c is not None:
        vis_rows += vrow("Search impression share", "is_", True, "Below 60% target" if is_c < .6 else "Healthy", f'<span class="sp {"hold" if is_c < .6 else "up"}">{"Raise reach" if is_c < .6 else "Maintain"}</span>')
        vis_rows += vrow("Lost IS (budget)", "lb", False, f"Budget limited on {n_budget} profitable campaign{'s' if n_budget != 1 else ''}" if n_budget else ("Budget is not the main limit" if (lb_c or 0) < .1 else "Budget limits reach"), f'<span class="sp {"up" if n_budget else "hold"}">{"Consider more budget" if n_budget else "Hold"}</span>')
        vis_rows += vrow("Lost IS (rank)", "lr", False, "Ad rank is lower than competitors" if (lr_c or 0) >= .3 else "Rank is competitive", f'<span class="sp {"down" if (lr_c or 0) >= .3 else "up"}">{"Improve ads and bids" if (lr_c or 0) >= .3 else "Maintain"}</span>')
    vis_box = (f'<div class="box"><h2>Search visibility</h2><p class="sub">Eligible impressions won or lost, last 30 days vs the 30 before.</p><div class="tw"><table class="sx"><thead><tr><th>Metric</th><th>Current</th><th>Change</th><th>Suggestion</th></tr></thead><tbody>{vis_rows}</tbody></table></div></div>'
               if vis_rows else '<div class="box"><h2>Search visibility</h2><p class="sub">Not supported by the current source for these campaigns.</p></div>')
    three = f'<section style="margin-bottom:14px">{chart_box}</section><section class="two">{pace}{vis_box}</section>'

    # ---------- RAG helper for traffic-quality metrics (CTR, CPC, CVR, Google ROAS)
    _fam = p["family"]["30"]; AVGCPC = (_fam["spend"] / _fam["clicks"]) if _fam["clicks"] else None
    def qc(kind, v, clicks, avg=None, conv=None, spend=None):
        if v is None or (clicks or 0) < 5: return "none"
        if kind == "ctr": return "g" if v >= .05 else ("y" if v >= .02 else "r")
        if kind == "cvr": return "none" if clicks < 10 else ("g" if v >= .03 else ("y" if v >= .01 else "r"))
        if kind == "cpc":
            if not avg: return "none"
            return "g" if v <= avg * .8 else ("r" if v >= avg * 1.5 else "y")
        if kind == "roas":
            if (spend or 0) < 3: return "none"
            if not conv: return "r"
            return "g" if v >= BE * 1.2 else ("y" if v >= BE else "r")
        return "none"

    QKEY = '<p class="key"><span class="p g">Good</span><span class="p y">Average</span><span class="p r">Poor</span><span>CTR 5%+ / 2%+, CVR 3%+ / 1%+, CPC under 80% / over 150% of the average, ROAS vs break-even. Red spend or conversions = money spent with no sale. Needs 5+ clicks to be rated.</span></p>'

    # ---------- main table
    def hv(r, spend_note):
        r_, sp = r
        if r_ is None: return '<span class="hv n" title="Under $20 spend in this window">–</span>'
        c = {"g": "g", "y": "y", "r": "r"}[rcls(r_)]
        return f'<span class="hv {c}" title="ROAS {r_:.2f}x on {fm(sp)} spend. Green is 20% or more above break-even {BE:.2f}x, amber is at or above break-even, red is below.">{r_:.2f}x</span>'
    def hcell(m):
        cap = [("7 days", m["h7"]), ("15 days", m["h15"]), ("30 days", m["h30"]), ("Last run" if not m["act"] else "Current run", m["lr"]), ("Lifetime", m["lh"])]
        chips = "".join(f'<span class="hch"><span class="hcap">{c}</span>{hv(v_, "")}</span>' for c, v_ in cap)
        last = ""
        if not m["act"]:
            last = f'<span class="hlast">Paused. Last spend {m["ls"].strftime("%-d %b")}</span>' if m["ls"] else '<span class="hlast">Paused, no spend</span>'
        return f'<td class="s1 hc"><span class="hcs">{chips}</span>{last}</td>'
    def sigrow(sg, fl):
        x = fl or sg
        return f'<span class="sigrow"><span class="sp {x[0]}" title="{esc(x[2])}">{x[1]}</span><small>{esc(x[2])}</small></span>' if x else ""
    def rkcol(pos, n):
        if not pos or n <= 1: return "n"
        if n == 2: return "g" if pos == 1 else "y"
        f = (pos - 1) / (n - 1)
        return "g" if f <= 1 / 3 else ("r" if f >= 2 / 3 else "y")
    def rkrow(rk):
        if rk is None: return '<span class="rkrow"><span class="rkl">Not ranked, under $20 spend</span></span>'
        ch = "".join((f'<span class="rkc {rkcol(rk["r" + k], rk["n" + k])}" title="Rank on the last {k} days alone, out of {rk["n" + k]}. Score {rk["sc" + k]}">{c} #{rk["r" + k]} · {rk["sc" + k]}</span>' if rk["r" + k] else f'<span class="rkc n" title="Under $20 spend in this window">{c} –</span>') for c, k in (("7d", "7"), ("15d", "15"), ("30d", "30")))
        sc = rk.get("sc"); scc = "g" if sc >= 67 else ("y" if sc >= 34 else "r")
        return f'<span class="rkrow"><span class="rkl">Score <span class="p {scc}" title="0 to 100. 70% profit rank, 30% ROAS rank among peers; 60% last 30 days, 40% last 7 days.">{sc}</span> Rank <b>#{rk["rank"]}</b> of {rk["n"]}</span>{ch}</span>'
    def rkrow_p(m):
        r = m.get("rr")
        return f'<span class="rkrow"><span class="rkl">Reopen rank <b>#{r["k"]}</b> of {r["n"]}</span></span>' if r else ""
    def pcells(m, k, c):
        x = m[k]; pv = m.get("p" + k)
        if x["spend"] <= 0 and x["base"] <= 0:
            return "".join(f'<td class="{"s1 " if i == 0 else ""}c{c}" data-l="{lbl}">—</td>' for i, lbl in enumerate(("spend", "revenue", "ROAS", "profit")))
        rc = rcls(x["roas"]) if x["spend"] > 0 else "none"
        pc_ = ("g" if x["profit"] > 0 else "r") if abs(x["profit"]) > .005 else "none"
        return (f'<td class="s1 c{c}" data-l="spend">{fm(x["spend"])}{arrow(x["spend"], pv["spend"], None) if pv and pv["spend"] else ""}</td>'
                f'<td class="c{c}" data-l="revenue">{fm(x["base"])}{arrow(x["base"], pv["base"], True) if pv and pv["base"] else ""}</td>'
                f'<td class="c{c}" data-l="ROAS"><span class="p {rc}">{rx(x["roas"])}</span>{arrow(x["roas"], pv["roas"], True) if pv and pv["roas"] is not None and x["roas"] is not None else ""}</td>'
                f'<td class="c{c}" data-l="profit"><span class="p {pc_}">{fm(x["profit"])}</span>{arrow(x["profit"], pv["profit"], True) if pv and pv["spend"] else ""}</td>')
    def scline(m):
        rk = m.get("rank")
        if not (m["act"] and rk): return ""
        col = lambda v: "g" if v >= 67 else ("y" if v >= 34 else "r")
        def box(cap, v, title=""):
            return f'<span class="scx" title="{title}"><i>{cap}</i><b class="hv {col(v) if v is not None else "n"}">{v if v is not None else "–"}</b></span>'
        return ('<span class="scl">' + box("Score", rk["sc"], "0 to 100. 70% profit rank + 30% ROAS rank among peers; overall = 60% last 30 days + 40% last 7 days.")
                + "".join(box(f'{l} #{rk["r" + k]}' if rk["r" + k] else l, rk.get("sc" + k) if rk["r" + k] else None, f'Score on the last {k} days alone') for l, k in (("7d", "7"), ("15d", "15"), ("30d", "30")))
                + f'<small>Rank #{rk["rank"]} of {rk["n"]}</small></span>')
    def scell(m):
        rk = m.get("rank")
        if m["act"] and rk:
            sc = rk["sc"]; scc = "g" if sc >= 67 else ("y" if sc >= 34 else "r")
            chips = "".join((f'<span class="hch"><span class="hcap">{lbl} #{rk["r" + k]}</span><span class="hv {"g" if rk["sc" + k] >= 67 else ("y" if rk["sc" + k] >= 34 else "r")}">{rk["sc" + k]}</span></span>' if rk["r" + k] else f'<span class="hch"><span class="hcap">{lbl}</span><span class="hv n">–</span></span>') for lbl, k in (("7d", "7"), ("15d", "15"), ("30d", "30")))
            return (f'<td class="s1 hc" title="0 to 100. 70% profit rank + 30% ROAS rank among peers; overall = 60% last 30 days + 40% last 7 days. Chips show each window alone.">'
                    f'<span class="scb"><span class="hv {scc} big">{sc}</span><small>Overall score<br>Rank #{rk["rank"]} of {rk["n"]}</small></span><span class="hcs">{chips}</span></td>')
        return '<td class="s1 hc"><span class="hlast">Not ranked</span></td>'
    def tcells(m):
        out = ""
        for key, c in (("7", "w"), ("30", "m")):
            w = m[key]
            if w["spend"] <= 0 or (w["clicks"] or 0) <= 0:
                out += "".join(f'<td class="{"s1 " if i == 0 else ""}c{c}">—</td>' for i in range(4))
                continue
            out += (f'<td class="s1 c{c}"><span class="p {qc("ctr", w["ctr"], w["clicks"])}">{pct(w["ctr"], 1)}</span></td>'
                    f'<td class="c{c}"><span class="p {qc("cpc", w["cpc"], w["clicks"], AVGCPC)}">{fm(w["cpc"], 2)}</span></td>'
                    f'<td class="c{c}"><span class="p {qc("cvr", w["cvr"], w["clicks"])}">{pct(w["cvr"], 1)}</span></td>'
                    f'<td class="c{c}"><span class="p {qc("roas", w["groas"], w["clicks"], conv=w["conv"], spend=w["spend"])}">{rx(w["groas"])}</span></td>')
        return out
    def prow_(cls_, name, m, attrs=""):
        return f'<tr class="{cls_}"{attrs}>{name}' + hcell(m) + "".join(pcells(m, k, c) for k, c, _ in PERIODS) + "</tr>"
    trs = ""; first_p = True
    for i, m in enumerate(p["table"]):
        cls_ = "cp act" if m["act"] else "cp paused"
        if not m["act"] and first_p: cls_ += " firstp"; first_p = False
        btn = '<button type="button" class="xp" aria-expanded="false" aria-label="Show ad groups">&#9656;</button>' if m["kids"] else '<span class="xp0"></span>'
        w30 = m["30"]
        def qline(lbl, w):
            if w["spend"] <= 0: return ""
            return (f'<span class="dtl"><b>{lbl}</b> CTR <span class="p {qc("ctr", w["ctr"], w["clicks"])}">{pct(w["ctr"], 1)}</span> CPC <span class="p {qc("cpc", w["cpc"], w["clicks"], AVGCPC)}">{fm(w["cpc"], 2)}</span> '
                    f'CVR <span class="p {qc("cvr", w["cvr"], w["clicks"])}">{pct(w["cvr"], 1)}</span> ROAS <span class="p {qc("roas", w["groas"], w["clicks"], conv=w["conv"], spend=w["spend"])}">{rx(w["groas"])}</span></span>')
        dtl = qline("7d", m["7"]) + qline("30d", m["30"])
        nm = (f'<th scope="row" title="First spend {m["launched"] or "n/a"}"><div class="nmrow">{btn}<span class="nmw"><span class="nm">{esc(m["short"])}</span>'
              f'<span class="meta"><span class="st {"on" if m["act"] else "off"}">{"Active" if m["act"] else "Paused"}</span><span class="ln2">{esc((m["type"] or "").replace("_", " ").title())}</span>' + (f'<span class="ln2">{len(m["kids"])} ad group{"s" if len(m["kids"]) != 1 else ""}</span>' if m["kids"] else "") + '</span>'
              + (sigrow(m.get("sig"), m.get("flag")) + scline(m) if m["act"] else sigrow(None, m.get("flag")) + rkrow_p(m)) + '</span></div></th>')
        trs += '<tbody class="grp">' + prow_(cls_, nm, m, f' data-id="c{i}"')
        for x in m["kids"]:
            an = (f'<th scope="row" class="asn"><div class="asw"><div class="asb"><span class="nm">{esc(x["name"])}</span><span class="meta"><span class="st {"on" if x["act"] else "off"}">{"Active" if x["act"] else "Paused"}</span><span class="st off" title="Shopify cannot attribute orders to an ad group, so revenue here is Google\'s conversion value">Google value</span></span>'
                  + (sigrow(x.get("sig"), x.get("flag")) + scline(x) if x["act"] else sigrow(None, x.get("flag")) + rkrow_p(x)) + '</div></div></th>')
            trs += prow_("as" + ("" if x["act"] else " paused"), an, x, f' data-p="c{i}" hidden')
        trs += "</tbody>"
    ua = p["unattr"]
    un_name = '<th scope="row"><div class="nmrow"><span class="xp0"></span><span class="nmw"><span class="nm">Unattributed Google orders</span><span class="meta">Google order known, campaign unknown. Revenue only, no spend can be assigned.</span></span></div></th>'
    un_cells = ""
    for k, c, _ in PERIODS:
        x = ua[k]
        if x["rev"] <= 0:
            un_cells += "".join(f'<td class="{"s1 " if j == 0 else ""}c{c}">—</td>' for j in range(4))
        else:
            un_cells += f'<td class="s1 c{c}">—</td><td class="c{c}">{fm(x["rev"])}</td><td class="c{c}">—</td><td class="c{c}">—</td>'
    trs += f'<tbody><tr class="un">{un_name}<td class="s1 hc"></td>{un_cells}</tr></tbody>'
    fm_ = p["family"]
    trs += '<tbody><tr class="total"><th scope="row">All tracked campaigns</th><td class="s1"></td>' + "".join(pcells(fm_, k, c) for k, c, _ in PERIODS) + "</tr></tbody>"
    cap = lambda k: (D.fromisoformat(P[k]["from"]).strftime("%a %-d %b") if k == "yesterday" else D.fromisoformat(P[k]["from"]).strftime("%-d %b") + " to " + D.fromisoformat(P[k]["to"]).strftime("%-d %b"))
    heads = "".join(f'<th colspan="4" class="s1 gh c{c}">{l}<small>{cap(k)}</small></th>' for k, c, l in PERIODS)
    heads = heads.replace(f'<small>{cap("life")}</small>', f'<small>Since {D.fromisoformat(P["life"]["from"]).strftime("%-d %b %Y")}</small>')
    sub = "".join(f'<th class="s1 c{c}">Spend</th><th class="c{c}">Revenue</th><th class="c{c}">ROAS</th><th class="c{c}">Profit</th>' for _, c, _ in PERIODS)
    table = f'''<div class="wrapx"><div class="wrap"><nav class="jump" aria-label="Jump to a period"><button type="button" class="stp" data-step="-1" aria-label="Previous">&#8249;</button><button type="button" data-i="0">Health</button><button type="button" data-i="1">Yesterday</button><button type="button" data-i="2">7 days</button><button type="button" data-i="3">15 days</button><button type="button" data-i="4">30 days</button><button type="button" data-i="5">Lifetime</button><button type="button" class="stp" data-step="1" aria-label="Next">&#8250;</button></nav><table>
<thead><tr><th rowspan="2" class="hcamp">Campaign</th><th rowspan="2" class="s1 hh">Health<small>Window ROAS vs break-even {BE:.2f}x. Run = latest stretch of spend, no gap over 3 days</small></th>{heads}</tr><tr>{sub}</tr></thead>
{trs}</table></div></div>'''
    # ---------- Traffic quality: its own table, filtered by period
    def trow(name, w, cls_="", sub_=""):
        if w["spend"] <= 0 and (w["clicks"] or 0) <= 0:
            return f'<tr class="{cls_}"><th scope="row">{name}</th>' + '<td colspan="8" class="muted" style="text-align:left">No spend in this period</td></tr>'
        return (f'<tr class="{cls_}"><th scope="row">{name}</th><td>{fm(w["spend"])}</td><td>{n0(w["impr"])}</td><td>{n0(w["clicks"])}</td>'
                f'<td><span class="p {qc("ctr", w["ctr"], w["clicks"])}">{pct(w["ctr"], 1)}</span></td><td><span class="p {qc("cpc", w["cpc"], w["clicks"], AVGCPC)}">{fm(w["cpc"], 2)}</span></td>'
                f'<td><span class="p {qc("cvr", w["cvr"], w["clicks"])}">{pct(w["cvr"], 1)}</span></td><td>{n1(w["conv"])}</td>'
                f'<td><span class="p {qc("roas", w["groas"], w["clicks"], conv=w["conv"], spend=w["spend"])}">{rx(w["groas"])}</span></td></tr>')
    def ttab(k):
        body = ""
        for m in p["table"]:
            if m[k]["spend"] <= 0 and (m[k]["clicks"] or 0) <= 0 and not m["act"]: continue
            body += trow(f'<span class="nm">{esc(m["short"])}</span><span class="meta"><span class="st {"on" if m["act"] else "off"}">{"Active" if m["act"] else "Paused"}</span></span>', m[k], "cp")
            for x in m["kids"]:
                if x[k]["spend"] > 0: body += trow(f'<span class="nm kid">{esc(x["name"])}</span>', x[k], "as")
        body += trow('<span class="nm">All tracked campaigns</span>', p["family"][k], "total")
        return (f'<div class="tw"><table class="sx trf"><thead><tr><th>Campaign</th><th>Spend</th><th>Impr.</th><th>Clicks</th><th>CTR</th><th>CPC</th><th>CVR</th><th>Conv.</th><th>Google ROAS</th></tr></thead><tbody>{body}</tbody></table></div>')
    traffic = ('<section class="box"><h2>Traffic quality</h2><p class="sub">Are the right people clicking, and do they buy? CTR, CPC, CVR and Google ROAS for every campaign and ad group. Google basis (Shopify cannot see clicks).</p>'
               '<div style="margin-bottom:8px">' + "".join(f'<button type="button" class="chip{" on" if k == "30" else ""}" data-g="trf" data-w="{k}">{l}</button>' for k, l in (("7", "7 days"), ("15", "15 days"), ("30", "30 days")))
               + "</div>" + QKEY + "".join(f'<div data-grp="trf" data-w="{k}"{"" if k == "30" else " hidden"}><p class="rg" style="margin:0 0 6px">{cap(k)}</p>{ttab(k)}</div>' for k in ("7", "15", "30")) + "</section>")
    howto = f'''<details class="how"><summary>How to read health, rank, signal and flags</summary><dl>
<dt>Revenue and ROAS</dt><dd>Campaign revenue is Shopify matched revenue (after refunds, cancelled orders excluded); ROAS = that revenue ÷ ad spend. Ad-group rows can only show Google's own conversion value because Shopify orders are not tied to ad groups. Orders with a Google signal but no campaign sit in the Unattributed row and count in the total.</dd>
<dt>Health</dt><dd>ROAS for the last 7, 15 and 30 days, the current (or last) run, and lifetime. Green is 20% or more above break-even ({BE:.2f}x), amber is at or above break-even, red is below it. Under $20 spend in a window shows a dash. Overall health: Good = 30-day green and 7-day at or above break-even; Poor = 30-day below break-even or no revenue; otherwise Watch.</dd>
<dt>Rank</dt><dd>Among active campaigns (ad groups rank inside their campaign). Score = 70% profit $ + 30% ROAS; overall blends 30 days (60%) and 7 days (40%). Green top third, red bottom third. Under $20 spend in a window is not ranked.</dd>
<dt>Spend signal</dt><dd><b>Spend more</b>: health Good, 7-day ROAS at or above 30-day, and 7-day profit positive. <b>Spend less</b>: health Poor, or 7-day ROAS below break-even. <b>Hold</b> otherwise, and also when Google shows a profitable ROAS but Shopify matches under half of its value (a tracking gap, so the owner number is not trusted).</dd>
<dt>Flags</dt><dd><b>Close #1</b> (active): health red or amber, 7-day not green, $20+ spent in 30 days, bottom half of its group; #1 is the worst. <b>Reopen #1</b> (paused): lifetime ROAS 20% above break-even over 5+ spend days and $50+; best first. <b>Keep closed</b>: lifetime ROAS below break-even.</dd>
<dt>Periods</dt><dd>Yesterday is the previous completed Melbourne day. All periods end on it; arrows compare with the period before. Today is never included.</dd></dl></details>'''
    keyrow = '<p class="key"><button class="tg" id="xa" type="button" data-o="0">Expand all ad groups</button><span class="p g">ROAS 20%+ above break-even</span><span class="p y">At or above break-even</span><span class="p r">Below break-even</span><span>▲▼ change vs the previous period: green is better, red is worse, grey is spend</span></p>'

    # ---------- Attribution: accuracy, tracked vs non-tracked value, order by order
    R = p["recon"]; TK = p["trk"]
    rk_ = [("yesterday", "t", "Yesterday"), ("7", "w", "7 days"), ("15", "x", "15 days"), ("30", "m", "30 days"), ("life", "l", "Lifetime")]
    def accp(v):
        if v is None: return "—"
        c = "g" if v >= .8 else ("y" if v >= .5 else "r")
        return f'<span class="p {c}">{v * 100:.0f}%</span>'
    def arow(lbl, fn, hint=""):
        return f'<tr><th scope="row">{lbl}{("<small>" + hint + "</small>") if hint else ""}</th>' + "".join(f'<td class="c{c}">{fn(TK[k], R.get(k))}</td>' for k, c, _ in rk_) + "</tr>"
    acc = f'''<div class="box"><h2>Tracking accuracy and tracked value</h2><p class="sub">How much of what Google claims Shopify can see, and how much of the counted revenue came with proper tracking.</p>
<div class="tw"><table class="mini attr"><thead><tr><th></th>{"".join(f'<th class="c{c}">{l}</th>' for _, c, l in rk_)}</tr></thead><tbody>
{arow("Google conversion value", lambda t, r: fm(t["g_val"]), "What Google Ads reports")}
{arow("Shopify revenue counted to Google", lambda t, r: fm(t["total_rev"]) + f'<small class="inl">{t["total_orders"]} order{"s" if t["total_orders"] != 1 else ""}</small>', "Orders we credit to Google Ads")}
{arow("Tracking accuracy", lambda t, r: accp(t["accuracy"]), "Smaller of the two values ÷ the larger. 80%+ good, 50%+ average")}
{arow("Tracked value", lambda t, r: f'<span class="p g">{fm(t["t_rev"])}</span><small class="inl">{t["t_orders"]} order{"s" if t["t_orders"] != 1 else ""}</small>' if t["t_orders"] else "—", "Shopify recorded a Google paid click (UTM or gclid)")}
{arow("Non-tracked value", lambda t, r: f'<span class="p {"y" if t["n_orders"] else "none"}">{fm(t["n_rev"])}</span><small class="inl">{t["n_orders"]} order{"s" if t["n_orders"] != 1 else ""}</small>' if t["n_orders"] else "—", "No click data in Shopify; counted through custom.order_source")}
{arow("Tracked share of revenue", lambda t, r: accp(t["tracked_share"]), "Tracked value ÷ counted revenue")}
{arow("Credited to a campaign", lambda t, r: f'{r["camp_orders"]} · {fm(r["camp_rev"])}' if r else "—")}
{arow("Unattributed (campaign unknown)", lambda t, r: f'{r["un_orders"]} · {fm(r["un_rev"])}' if r else "—")}
</tbody></table></div><p class="sub" style="margin-top:8px">Confidence <b>{esc(conf["level"])}</b>: {esc(conf["why"])} Campaign-credited + unattributed = counted revenue, always.</p></div>'''
    def yn(v, good=True):
        return f'<span class="p {"g" if v else ("r" if good else "none")}">{"Yes" if v else "No"}</span>'
    def under(o):
        if not o["counted"]:
            return f'<span class="p r">Not counted</span> <small>{esc(o["why"])}</small>'
        if o["has_utm"] and o["camp"] and o["tier"] in ("Exact", "Strong"):
            return f'UTM campaign <small>{esc(o["tier"])}</small>'
        if o["src_google"]:
            return f'custom.order_source <small>"{esc(o["source"])}"</small>'
        if o["gclid"]:
            return 'gclid click only'
        return '—'
    last30 = [o for o in p["orders"] if not o["cancelled"]]
    def otable(rows):
        if not rows: return '<p class="muted">No orders with a Google signal in this window.</p>'
        body = "".join(f'<tr class="{"hot" if not o["counted"] else ""}"><th scope="row">{esc(o["name"])}<small>{D.fromisoformat(o["date"]).strftime("%a %-d %b")}</small></th><td>{fm(o["net"])}</td><td>{yn(o["counted"])}</td><td>{yn(o["trk"])}</td><td>{yn(o["has_utm"])}</td><td class="tl">{under(o)}</td><td class="tl">{esc(short_name(o["camp"]) if o["camp"] else "Unattributed" if o["counted"] else "—")}<small>{esc(o["tier"])}</small></td></tr>' for o in rows)
        return f'<div class="tw ot"><table class="sx"><thead><tr><th>Order</th><th>Value</th><th>Google Ads attributed</th><th>Tracked in Shopify</th><th>UTM available</th><th>Counted under</th><th>Campaign</th></tr></thead><tbody>{body}</tbody></table></div>'
    d7 = (yd - dt.timedelta(days=6)).isoformat()
    ord_box = (f'<div class="box"><h2>Order by order</h2><p class="sub">Every order with a Google signal. <b>Attributed</b>: we credit it to Google Ads. <b>Tracked in Shopify</b>: Shopify recorded a Google paid click. <b>UTM available</b>: the click carried a campaign tag. <b>Counted under</b>: what made us count it.</p>'
               '<div style="margin-bottom:8px">' + "".join(f'<button type="button" class="chip{" on" if k == "30" else ""}" data-g="ord" data-w="{k}">{l}</button>' for k, l in (("7", "7 days"), ("30", "30 days"))) + '</div>'
               + f'<div data-grp="ord" data-w="7" hidden>{otable([o for o in last30 if o["date"] >= d7])}</div><div data-grp="ord" data-w="30">{otable(last30)}</div>'
               + f'<p class="old">Unresolved UTM tags: {esc(", ".join(f"{k} ({v})" for k, v in list(p["unresolved_utms"].items())[:4]) or "none")}.</p></div>')
    # ---- Google conversions matched to Shopify orders (by value)
    GS = p["gsum"]; GM = p["gmatch"]
    def gblock(k):
        x = GS[k]
        tot = x["val"]
        def pc_(v): return f'{v / tot * 100:.0f}%' if tot > 0 else "—"
        def line(lbl, hint, n, v, tone, strong=False):
            return (f'<tr class="{"total" if strong else ""}"><th scope="row">{lbl}<small>{hint}</small></th><td>{n}</td><td><span class="p {tone}">{fm(v)}</span></td><td><span class="p {tone}">{pc_(v)}</span></td></tr>')
        ok = abs(x["v_ct"] + x["v_cn"] + x["v_mu"] + x["v_mx"] + x["v_none"] - tot) < 0.01
        return (f'<div class="tw"><table class="mini attr rec"><thead><tr><th>Google reported value, split</th><th>Conv.</th><th>Value</th><th>% of Google</th></tr></thead><tbody>'
                + line("Google reported", "All conversions Google claims in this period", x["n"], tot, "none", True)
                + line("Counted: tracked", "Order is in our Google revenue and Shopify saw the Google click (UTM or gclid)", x["n_ct"], x["v_ct"], "g")
                + line("Counted: non-tracked", "Order is in our Google revenue, but only through custom.order_source (no click data)", x["n_cn"], x["v_cn"], "g")
                + line("Attribution missing: no UTM", "Matching order exists but Shopify has no Google UTM, so it is labelled Organic, Direct, Repeat or another source", x["n_mu"], x["v_mu"], "y" if x["n_mu"] else "none")
                + line("Attribution missing: other channel", "Order carries a Google UTM but its source says another channel, so it is held back", x["n_mx"], x["v_mx"], "y" if x["n_mx"] else "none")
                + line("Remaining: no order found", "No Shopify order at that value around that date", x["n_none"], x["v_none"], "r" if x["n_none"] else "none")
                + f'<tr><th scope="row">Check<small>The five lines above add up to Google reported</small></th><td></td><td colspan="2"><span class="p {"g" if ok else "r"}">{"Adds up" if ok else "Does not add up"}</span></td></tr>'
                + f'<tr><th scope="row">Our counted orders that match a Google conversion<small>Order totals, so a little above Google\'s subtotal values (shipping)</small></th><td>{x["n_mc"]}</td><td colspan="2">{fm(x["v_mc"])}</td></tr>'
                + f'<tr><th scope="row">Counted by us but not reported by Google<small>Credited to Google by us (mostly order source only); Google shows no matching conversion</small></th><td>{x["n_extra"]}</td><td colspan="2">{fm(x["v_extra"])}</td></tr>'
                + f'<tr class="total"><th scope="row">Revenue we count for Google<small>This is the revenue profit and ROAS use</small></th><td>{x["n_mc"] + x["n_extra"]}</td><td colspan="2">{fm(x["our_rev"])}</td></tr>'
                + '</tbody></table></div>')
    RES = {"counted": ("g", "Counted"), "other_campaign": ("y", "Counted, other campaign"), "missing": ("y", "Attribution missing"), "none": ("r", "No order found")}
    share = lambda g: "" if g["ncand"] <= 1 else " · " + str(g["ncand"]) + " orders share this value"
    def gtable(rows):
        if not rows: return '<p class="muted">No Google conversions in this window.</p>'
        body = ""
        for g in rows:
            c, lab = RES[g["res"]]
            if g["order"]:
                od = f'{esc(g["order"])}<small>{D.fromisoformat(g["odate"]).strftime("%a %-d %b")} · {fm(g["onet"])} total · {fm(g["osub"]) if g["osub"] is not None else "subtotal n/a"} subtotal</small>'
                src = f'{esc(g["source"] or "no source")}<small>{"Google UTM present" if g["utm"] else "no Google UTM"}{share(g)}</small>'
                us = esc(short_name(g["ocamp"])) + f'<small>{esc(g["tier"])}</small>' if g["counted"] and g["ocamp"] else ("Unattributed" if g["counted"] else "Not credited to Google")
            else:
                od = '<span class="muted">No Shopify order at this value</span>'; src = "—"; us = "—"
            body += f'<tr class="{"hot" if g["res"] == "none" else ""}"><th scope="row">{D.fromisoformat(g["date"]).strftime("%a %-d %b")}<small>{esc(short_name(g["camp"]))}</small></th><td>{fm(g["val"])}</td><td class="tl">{od}</td><td class="tl">{src}</td><td class="tl">{us}</td><td><span class="p {c}">{lab}</span></td></tr>'
        return f'<div class="tw ot"><table class="sx"><thead><tr><th>Google conversion</th><th>Value</th><th>Possible Shopify order</th><th>Order source (custom.order_source)</th><th>Our attribution</th><th>Result</th></tr></thead><tbody>{body}</tbody></table></div>'
    d7s = (yd - dt.timedelta(days=6)).isoformat()
    if p["gm_ok"] and GM:
        gm_box = (f'<div class="box"><h2>Google conversions matched to Shopify orders</h2><p class="sub">Google does not expose which order a conversion was, but its conversion value is the order subtotal (total minus shipping). So each Google conversion is matched to the Shopify order with the same value on the same day, or the day either side. These are <b>possible matches</b>, not proof, and they never change revenue or profit above. <b>Attribution missing</b> means the order exists but Shopify labelled it Organic, Direct, Repeat or another channel.</p>'
                  '<div style="margin-bottom:8px">' + "".join(f'<button type="button" class="chip{" on" if k == "30" else ""}" data-g="gm" data-w="{k}">{l}</button>' for k, l in (("7", "7 days"), ("30", "30 days"), ("life", "Lifetime"))) + '</div>'
                  + "".join(f'<div data-grp="gm" data-w="{k}"{"" if k == "30" else " hidden"}>{gblock(k)}{gtable([g for g in GM if (k != "7" or g["date"] >= d7s)] if k != "life" else [g for g in GM])}</div>' for k in ("7", "30", "life"))
                  + '<p class="old">Table shows the last 30 days; Lifetime totals above cover the whole history.</p></div>')
    else:
        gm_box = '<div class="box"><h2>Google conversions matched to Shopify orders</h2><p class="muted">Google conversion-by-date data was unavailable on the last refresh.</p></div>'
    two = f'<section><h2 class="sh">Attribution</h2>{gm_box}{acc}{ord_box}</section>'

    # ---------- search terms / keywords
    def sugg(x, kind):
        brand = bool(re.search(r"indi\s?feels", x.get("search_term") or x.get("keyword_text") or "", re.I))
        be = x["groas"] is not None and x["groas"] >= BE
        if x["conv"] == 0 and x["spend"] >= 5 and not brand: return ("down", "Add negatives" if kind == "st" else "Pause")
        if x["conv"] == 0 and x["clicks"] >= 10: return ("hold", "Review landing page")
        if x["conv"] > 0 and x["groas"] is not None and x["groas"] >= BE * 1.2: return ("up", "Increase bid")
        if x["conv"] > 0 and be: return ("up", "Keep")
        if x["conv"] > 0: return ("hold", "Watch margin")
        return ("hold", "Watch")
    def sxtable(rows, kind, limit):
        if rows is None: return '<p class="muted">Data unavailable: this source failed on the last refresh.</p>'
        if not rows: return '<p class="muted">No rows in this window.</p>'
        label = "Search term" if kind == "st" else "Keyword"
        body = ""
        _ts = sum(x["spend"] for x in rows); _tc = sum(x["clicks"] for x in rows); avg = (_ts / _tc) if _tc else None
        for x in rows[:limit]:
            sg = sugg(x, kind); nmv = x["search_term"] if kind == "st" else f'{x["keyword_text"]} <small>{esc((x["keyword_match_type"] or "").title())}</small>'
            body += f'<tr class="{"hot" if sg[1] in ("Add negatives", "Pause") else ""}"><th scope="row">{esc(nmv) if kind == "st" else nmv}<small>{esc(p["camp_meta"].get(x["campaign_id"], {}).get("short", ""))} · {esc(x["ad_group_name"])}</small></th><td><span class="p {"r" if x["conv"] == 0 and x["spend"] >= 5 else "none"}">{fm(x["spend"], 2)}</span></td><td>{n0(x["clicks"])}</td><td><span class="p {qc("ctr", x["ctr"], x["clicks"])}">{pct(x["ctr"], 1)}</span></td><td><span class="p {("g" if x["conv"] > 0 else ("r" if x["spend"] >= 3 else "none"))}">{n1(x["conv"])}</span></td><td><span class="p {qc("cvr", x["cvr"], x["clicks"])}">{pct(x["cvr"], 1)}</span></td><td><span class="p {qc("cpc", x["cpc"], x["clicks"], avg)}">{fm(x["cpc"], 2)}</span></td><td><span class="p {qc("roas", x["groas"], x["clicks"], conv=x["conv"], spend=x["spend"])}">{rx(x["groas"])}</span></td><td><span class="sp {sg[0]}">{sg[1]}</span></td></tr>'
        return f'<div class="tw"><table class="sx"><thead><tr><th>{label}</th><th>Spend</th><th>Clicks</th><th>CTR</th><th>Conv.</th><th>CVR</th><th>CPC</th><th>Google ROAS</th><th>Suggestion</th></tr></thead><tbody>{body}</tbody></table></div>'
    def sx_box(title, key, kind, sub_):
        out = f'<div class="box"><h2>{title}</h2><p class="sub">{sub_}</p><div style="margin-bottom:8px">' + "".join(f'<button type="button" class="chip{" on" if k == "30" else ""}" data-g="{key}" data-w="{k}">{l}</button>' for k, l in (("7", "7 days"), ("15", "15 days"), ("30", "30 days"), ("life", "Lifetime"))) + "</div>" + QKEY
        for k in ("7", "15", "30", "life"):
            rows = p["drill"][key][k]
            out += f'<div data-grp="{key}" data-w="{k}"{"" if k == "30" else " hidden"}>{sxtable(rows, kind, 15)}' + (f'<details class="how" style="margin-top:8px"><summary>Show all {len(rows)}</summary>{sxtable(rows[15:60], kind, 45)}</details>' if rows and len(rows) > 15 else "") + "</div>"
        return out + "</div>"
    wasted = p["waste_total"]
    sxs = f'<section class="two" style="grid-template-columns:1fr">{sx_box("Search terms", "search_terms", "st", "Actual queries that triggered your ads. ROAS here is Google's own figure (Shopify cannot see the search term). Red rows: spend with no conversions.")}{sx_box("Keywords", "keywords", "kw", "Keywords you are bidding on. Google basis; brand terms are never suggested for negatives.")}</section>'
    waste = f'<p class="foot" style="margin:0 0 12px"><b>{fm(wasted)}</b> spent on search terms with $5+ spend and no conversions ({"last 30 days" if p["waste_win"] == "30" else "lifetime" if p["waste_win"] else "n/a"}); brand terms excluded from the negatives list.</p>' if p["waste_win"] else ""

    # ---------- months
    mon = ""
    for m in p["months"]:
        if m["spend"] <= 0 and m["rev"] <= 0 and m["gval"] <= 0: continue
        gap = m["spend"] >= 100 and m["gval"] >= 2 * max(m["rev"], 1)
        rows_ = "".join(f'<tr><th scope="row">{D.fromisoformat(x["date"]).strftime("%a %-d")}</th><td>{fm(x["spend"], 2)}</td><td>{n1(x["conv"])}</td><td>{fm(x["gval"])}</td><td>{x["orders"]}</td><td>{fm(x["rev"])}</td><td class="{cls(x["rev"] - x["gval"])}">{fm(x["rev"] - x["gval"])}</td><td class="{cls(x["profit"])}">{fm(x["profit"], 2)}</td></tr>' for x in m["days"])
        mon += (f'<details class="how mo"><summary>{dt.date.fromisoformat(m["month"] + "-01").strftime("%B %Y")} · spend {fm(m["spend"])} · matched revenue {fm(m["rev"])} · profit <span class="{cls(m["profit"])}">{fm(m["profit"])}</span> · Google value {fm(m["gval"])}'
                + (' <span class="sp close">Tracking gap</span>' if gap else "") + f'</summary><div class="tw"><table class="sx"><thead><tr><th>Day</th><th>Spend</th><th>Google conv.</th><th>Google value</th><th>Shopify orders</th><th>Shopify matched</th><th>Δ revenue</th><th>Profit</th></tr></thead><tbody>{rows_}</tbody></table></div></details>')
    monthly = f'<div class="box" style="margin-bottom:14px"><h2>Month to day tracking</h2><p class="sub">Each month opens to its completed days. Today is never included.</p>{mon}</div>'

    method = f'''<details class="how"><summary>HOW PROFIT IS CALCULATED</summary>
<p><b>Profit = Shopify matched revenue ÷ 1.1 × 0.75 − Google spend − Google Ads expert fee</b>: revenue minus GST (1/11), minus product cost (25% of ex-GST revenue), minus ad spend, minus the expert fee of $155 a week ($22.14 a day, charged for every day in the period). The fee is an account cost, so campaign and ad-group rows show profit before it. Break-even ROAS is {BE:.2f}x.</p>
<ul><li>Revenue is the Shopify order total after refunds. Cancelled orders are excluded; partly refunded orders count at the remaining value.</li><li>Shipping cost is not deducted because no reliable shipping-cost data exists, so real profit is somewhat lower where postage is paid.</li>
<li>Owner ROAS = Shopify matched revenue ÷ Google spend. Google platform ROAS is shown beside it and never used for profit.</li><li>Tracked campaigns are Google campaigns whose name starts with "Tracked". Paused ones that spent in a window stay listed.</li>
<li>Lifetime starts {D.fromisoformat(p["life_start"]).strftime("%-d %b %Y")}, the first day with both tracked spend and Shopify order history; earlier spend cannot be matched to orders and is excluded.</li></ul></details>
<details class="how"><summary>Attribution and confidence levels</summary><ul><li><b>Exact</b>: the order's Google UTM campaign is a tracked campaign's id or exact name. <b>Strong</b>: an unambiguous shortened form of one campaign's name, or exact but the order source names another channel.</li>
<li><b>Probable</b>: Google click evidence or order source "Google Online Orders" on a day tracked campaigns spent. If only one tracked campaign was spending, it is assigned to it (inferred); otherwise it stays Unattributed.</li>
<li><b>Unmatched</b>: no Google signal, cancelled, Google calls or store visits (not campaign-trackable), or a Google UTM contradicted by another channel's order source. Never forced into a campaign. Each Shopify order id is counted once.</li></ul></details>
<details class="how"><summary>Diagnostics</summary><ul><li>Sources: {", ".join(f"{esc(k)} {'ok' if v.get('ok') else 'FAILED'}" for k, v in sorted(st.items()))}</li><li>Orders counted {p["attribution"]["total"]} (Exact {p["attribution"]["exact"]}, Strong {p["attribution"]["strong"]}, Probable {p["attribution"]["probable"]}), cancelled {p["attribution"]["cancelled"]}, offline Google {p["attribution"]["offline"]}; excluded: {esc(json.dumps(p["attribution"]["excluded"]))}</li>
<li>Google data through {p["data_through"]["google"]}; latest Shopify order {p["data_through"]["shopify"]}; completed through {p["data_through"]["completed"]}. Generated {esc(p["generated"])}.</li></ul></details>'''

    head = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Google Ads tracked report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Figtree:wght@400;500;600&display=swap" rel="stylesheet">
<style>
{css}
</style></head><body><main>
<header><div class="hd"><h1>Google Ads, tracked</h1><p>IndiFeels Google Ads account, tracked campaigns. Revenue is Shopify matched revenue, with Google's own figures beside it. Completed through {yd.strftime("%A %-d %B %Y")}, updated {gen.strftime("%-I:%M %p")} Melbourne time.</p></div><button class="tg" id="tg" type="button">Dark mode</button></header>'''
    t = p["today_block"]
    today_ = (f'<p class="foot" style="margin:0 0 14px"><b>Today, partial ({D.fromisoformat(t["date"]).strftime("%-d %b")}):</b> spend so far {fm(t["spend"], 2)}, {n0(t["clicks"])} clicks, {n1(t["conv"])} Google conversions, {t["orders"]} matched orders ({fm(t["rev"])}). Not a completed day; excluded from every figure on this page.</p>') if (t["has_google"] or t["orders"]) else ""
    body = kpis + sigp + strip + three + howto + keyrow + table + '<div style="height:14px"></div>' + traffic + two + waste + sxs + monthly + method
    return head + body + "</main>" + JS_THEME + "</body></html>"


def meta_for(p):
    P = p["periods"]
    sig = p["signal"]
    fn = front_numbers(p); wn = p["waiting"]["d7"]["n"]
    last = p["days"][-14:]
    out = {
        "updated": dt.datetime.fromisoformat(p["generated"]).strftime("%-d %b %Y, %-I:%M %p"),
        "stats": [
            [money(fn["spend"], 2), f"ad spend, {fn['day']}"],
            [money(fn["rev"]), f"revenue, {fn['day']}"],
            [money(fn["profit"]), f"profit, {fn['day']}"],
            [(format(fn["att"] * 100, ".0f") + "%") if fn["att"] is not None else "n/a", f"attribution, {fn['day']}"],
        ],
        "signal": {"code": "hold", "label": sig["code"], "reason": sig["headline"]},
        "spark": [[round(x["spend"], 2) for x in last], [round(x["rev"], 2) for x in last], [round(x["profit"], 2) for x in last], []],
    }
    if wn:
        out["warn"] = f"{wn} order{'s' if wn != 1 else ''} waiting for attribution (7 days)"
    return out


def main():
    src, out_html, out_meta = sys.argv[1:4]
    raw = json.load(open(src))
    p = compute(raw)
    problems = validate(p)
    if problems:
        for x in problems:
            print("VALIDATION FAILED:", x, file=sys.stderr)
        raise SystemExit(3)
    page = render(p)
    if len(page) < 5000 or "Budget signal" not in page:
        raise SystemExit("Rendered page failed sanity check")
    open(out_html, "w").write(page)
    json.dump(meta_for(p), open(out_meta, "w"), separators=(",", ":"))
    if len(sys.argv) > 4:
        json.dump(p, open(sys.argv[4], "w"), default=str)
    print("Google tracked report built: completed through", p["yesterday"], "| signal", p["signal"]["code"], "| confidence", p["confidence"]["level"],
          "| orders matched", p["attribution"]["total"])


if __name__ == "__main__":
    main()
