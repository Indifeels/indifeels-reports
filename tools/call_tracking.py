"""Build the "Call Tracking — Nimbata" report (HTML + tile summary). Presentation only: all numbers come from the
stable Supabase contract (sync_get_call_tracking), so redesigning this file never touches ingestion.

Usage: call_tracking.py DATA.json OUT.html OUT.meta.json

Rules this builder enforces (see docs/NIMBATA_INTEGRATION.md):
  * "Yesterday" is the previous Melbourne calendar day (the contract's own date boundaries), never a rolling 24 hours.
  * A value that is not available is shown as "Missing" — never as 0. A day with no calls once Nimbata is live IS a real 0.
  * Nothing is invented: qualified leads / values appear only when Nimbata supplied them; attribution uses Nimbata's fields.
"""
import html
import json
import sys
from collections import OrderedDict
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")
esc = lambda s: html.escape("" if s is None else str(s), quote=True)
MISS = '<span class="miss">Missing</span>'
LINES = ["Website", "GMB SYD", "GMB MEL", "Google Ads Paid"]   # the 4 Nimbata tracking numbers
ORIGINS = ["Google paid", "GMB paid", "GMB organic", "Google organic", "Meta", "Referral", "Website direct"]
LINE_COL = {"Website": "#2563eb", "GMB SYD": "#f59e0b", "GMB MEL": "#ec4899", "Google Ads Paid": "#16a34a"}
ORIGIN_COL = {"Google paid": "#16a34a", "GMB paid": "#db2777", "GMB organic": "#f97316", "Google organic": "#0ea5e9",
              "Meta": "#6366f1", "Referral": "#8b5cf6", "Website direct": "#64748b"}
LCOL = lambda ln: LINE_COL.get(ln, "#94a3b8")
OCOL = lambda o: ORIGIN_COL.get(o, "#94a3b8")
PERIODS = [("yesterday", "Yesterday"), ("last_7", "Last 7 days"), ("last_30", "Last 30 days"), ("lifetime", "Lifetime"), ("today_partial", "Today — partial")]
BREAK_PERIODS = [("yesterday", "Yesterday"), ("last_7", "Last 7 days"), ("last_30", "Last 30 days")]


def n0(v):
    return "{:,}".format(int(v))


def money(v):
    return "$" + "{:,.2f}".format(float(v)) if v is not None else MISS


def dur(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    return "%d:%02d" % (sec // 60, sec % 60)


def fmt_day(d, with_year=False):
    return d.strftime("%a %-d %b" + (" %Y" if with_year else ""))


def period_days(today, key):
    if key == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if key == "last_7":
        return today - timedelta(days=7), today - timedelta(days=1)
    if key == "last_30":
        return today - timedelta(days=30), today - timedelta(days=1)
    return today, today


def build(src):
    d = src["data"]
    fs = src.get("fetch_status", {})
    sample = bool(src.get("sample"))
    today = date.fromisoformat(d["today"])
    health = d.get("health", {})
    first = health.get("nimbata_first_data_day")
    first = date.fromisoformat(first) if first else None
    live = first is not None                      # Nimbata has delivered (or reconciled) real data
    summary = {r["period"]: r for r in d["summary"]}
    daily = {date.fromisoformat(r["day"]): r for r in d["nimbata_daily"]}
    day_status = {date.fromisoformat(k): v for k, v in (d.get("nimbata_day_status") or {}).items()}
    calls = d["calls"]
    for c in calls:
        c["_day"] = date.fromisoformat(c["day"]) if c.get("day") else None
        c["_dt"] = datetime.fromisoformat(c["started_at"].replace("Z", "+00:00")).astimezone(TZ) if c.get("started_at") else None
    updated = datetime.fromisoformat(src["now"]).astimezone(TZ).strftime("%-d %b %Y, %-I:%M %p")

    # ------------------------------------------------------------------ health banner
    notes = []
    if sample:
        notes.append(("warn", "SAMPLE DATA — layout preview only. Nothing on this page is a real call."))
    if not live:
        notes.append(("info", "Nimbata is not connected yet (setup pending) — Nimbata numbers show <b>Missing</b> until the first call arrives. This is a pending state, not an outage."))
    elif not health.get("nimbata_api_configured"):
        notes.append(("info", "Nimbata API reconciliation is not configured yet — numbers come from the live webhook only and previous-day figures are not API-verified."))
    for k, label in (("nimbata", "Nimbata API sync"), ("gmb", "Google Business Profile sync")):
        s = fs.get(k) or {}
        if s.get("ok") is False:
            notes.append(("bad", "%s failed (%s): %s. Showing the last good data." % (label, esc(s.get("category", "error")), esc(s.get("error", "")))))
    err = health.get("nimbata_last_error")
    if live and err and fs.get("nimbata", {}).get("ok") is not False and health.get("nimbata_last_api_ok") and err.get("at") and err["at"] > health["nimbata_last_api_ok"]:
        notes.append(("bad", "Latest Nimbata problem: %s — %s" % (esc(err.get("category", "")), esc(err.get("detail", "")))))
    banner = "".join('<div class="note %s">%s</div>' % (k, t) for k, t in notes)

    # ------------------------------------------------------------------ KPI tiles: calls per Nimbata tracking line
    def in_period(key):
        if key == "lifetime":
            return [c for c in calls if c["_day"]]
        a, b = period_days(today, key)
        return [c for c in calls if c["_day"] and a <= c["_day"] <= b]

    def prev_period(key):
        if key in ("yesterday", "last_7", "last_30"):
            a, b = period_days(today, key)
            n = (b - a).days + 1
            return a - timedelta(days=n), a - timedelta(days=1)
        return None

    def kpi_block(key):
        if not live:
            vals = [("Total calls", MISS, "#0f766e")] + [(ln, MISS, LCOL(ln)) for ln in LINES]
            return '<div class="kpis">' + "".join('<div class="kpi" style="--c:%s"><span class="l">%s</span><span class="v">%s</span></div>' % (c, l, v) for l, v, c in vals) + "</div>"
        rows = in_period(key)
        pp = prev_period(key)
        prev = [c for c in calls if c["_day"] and pp and pp[0] <= c["_day"] <= pp[1]] if pp else None

        def dl(n_now, n_prev):
            if prev is None or pp[0] < first:
                return ""
            d_ = n_now - n_prev
            cls = "up" if d_ > 0 else "dn" if d_ < 0 else "fl0"
            return '<span class="dl %s">%s %s vs previous</span>' % (cls, "▲" if d_ > 0 else "▼" if d_ < 0 else "■", abs(d_))
        cnt = {ln: sum(1 for c in rows if c.get("line") == ln) for ln in LINES}
        other = sum(1 for c in rows if c.get("line") not in LINES)
        rep_n = sum(1 for c in rows if c.get("repeat"))
        tiles = [("Total calls", n0(len(rows)), "#0f766e", dl(len(rows), len(prev) if prev is not None else 0), "%s repeat callers" % n0(rep_n), True)]
        for ln in LINES:
            tiles.append((ln, n0(cnt[ln]), LCOL(ln), dl(cnt[ln], sum(1 for c in (prev or []) if c.get("line") == ln)), "", False))
        if other:
            tiles.append(("Unmapped line", n0(other), "#94a3b8", "", "tracking number not matched", False))
        return '<div class="kpis">' + "".join('<div class="kpi%s" style="--c:%s"><span class="l">%s</span><span class="v">%s</span>%s%s</div>' % (
            " tot" if tot else "", col, lab, val, d_, '<span class="s">%s</span>' % sub if sub else "") for lab, val, col, d_, sub, tot in tiles) + "</div>"

    # ------------------------------------------------------------------ day-by-day calls per line
    by_day = {}
    for c in calls:
        if c["_day"]:
            by_day.setdefault(c["_day"], []).append(c)

    def nimbata_rows(n):
        out = []
        for i in range(n):
            day = today - timedelta(days=i)
            cls = "x30" if i >= 14 else ""
            label = fmt_day(day) + (' <small class="tag">today · partial</small>' if i == 0 else "")
            if not live or day < first:
                cells = "".join("<td>%s</td>" % MISS for _ in range(len(LINES) + 3))
                st = '<span class="chip m">Missing</span>'
            else:
                rows = by_day.get(day, [])
                cells = ""
                for ln in LINES:
                    n_ = sum(1 for c in rows if c.get("line") == ln)
                    cells += '<td class="heat" style="--c:%s;--p:%d%%">%s</td>' % (LCOL(ln), min(70, 12 + n_ * 14) if n_ else 0, ("<b>%d</b>" % n_) if n_ else "0")
                cells += "<td><b>%s</b></td><td>%s</td><td>%s</td>" % (n0(len(rows)), n0(sum(1 for c in rows if c.get("repeat"))), MISS)
                if i == 0:
                    st = '<span class="chip p">Partial</span>'
                elif day_status.get(day) == "final":
                    st = '<span class="chip f">Final</span>'
                else:
                    st = '<span class="chip w">Webhook only</span>'
            out.append('<tr class="%s"><th scope="row">%s</th>%s<td>%s</td></tr>' % (cls, label, cells, st))
        return "".join(out)

    nim_table = ('<div class="scroll"><table><thead><tr><th>Day (Melbourne)</th>%s<th>Total</th><th>Repeat callers</th><th>Direct dial*</th><th>Data</th></tr></thead><tbody>%s</tbody></table></div>') % (
        "".join('<th style="--c:%s" class="ldot">%s</th>' % (LCOL(ln), esc(ln)) for ln in LINES), nimbata_rows(30))


    # ------------------------------------------------------------------ stacked daily chart + hour-of-day
    def chart_html(n):
        if not live:
            return '<p class="empty">%s</p>' % MISS
        days = [today - timedelta(days=i) for i in range(n - 1, -1, -1)]
        mx = max([len(by_day.get(dd, [])) for dd in days] + [1])
        cols = ""
        for dd in days:
            t = len(by_day.get(dd, []))
            if dd < first:
                cols += '<div class="col miss-col" title="%s: Missing"><div class="stack"></div><span class="x">%d</span></div>' % (fmt_day(dd), dd.day)
                continue
            segs = "".join('<i style="height:%.1f%%;background:%s" title="%s %s: %d"></i>' % (
                100.0 * k / mx, LCOL(ln), fmt_day(dd), ln, k) for ln in LINES for k in [sum(1 for c in by_day.get(dd, []) if c.get("line") == ln)] if k)
            cols += '<div class="col" title="%s: %d calls"><b class="t">%s</b><div class="stack">%s</div><span class="x">%d</span></div>' % (fmt_day(dd), t, t or "", segs, dd.day)
        legend = "".join('<span class="lg"><i style="background:%s"></i>%s</span>' % (LCOL(ln), esc(ln)) for ln in LINES)
        return '<div class="legend">%s</div><div class="chart">%s</div>' % (legend, cols)

    def hours_html():
        if not live:
            return '<p class="empty">%s</p>' % MISS
        a_, b_ = period_days(today, "last_30")
        rows = [c for c in calls if c["_dt"] and c["_day"] and a_ <= c["_day"] <= b_]
        if not rows:
            return '<p class="empty">No calls in the last 30 days.</p>'
        hrs = [sum(1 for c in rows if c["_dt"].hour == h) for h in range(24)]
        mx = max(hrs)
        bars = "".join('<div class="hc" title="%s: %d calls"><i style="height:%.0f%%"></i><span>%s</span></div>' % (
            datetime(2000, 1, 1, h).strftime("%-I %p"), hrs[h], 100.0 * hrs[h] / mx, datetime(2000, 1, 1, h).strftime("%-I%p").lower() if h % 3 == 0 else "") for h in range(24))
        return '<div class="hours">%s</div>' % bars

    # ------------------------------------------------------------------ GMB day-by-day (separate table; call CLICKS + directions)
    gm = [r for r in d["gmb_daily"]]
    locs = OrderedDict()
    for r in sorted(gm, key=lambda r: (0 if "melbourne" in (r.get("location_title") or "").lower() else 1, r.get("location_title") or "")):
        locs.setdefault(r["location_id"], (r.get("location_title") or r["location_id"]).replace("Indifeels ", ""))
    gidx = {(date.fromisoformat(r["day"]), r["location_id"]): r for r in gm}

    def gcell(r, key):
        if r is None or not r["data_available"] or r.get(key) is None:
            return MISS, None
        return n0(r[key]), r[key]

    def gmb_rows(n):
        out = []
        for i in range(n):
            day = today - timedelta(days=i)
            cls = "x30" if i >= 14 else ""
            cells, tc, td, any_prov, any_data, any_missing = "", 0, 0, False, False, False
            for lid in locs:
                r = gidx.get((day, lid))
                a, av = gcell(r, "call_clicks")
                b, bv = gcell(r, "direction_requests")
                cells += "<td>%s</td><td>%s</td>" % (a, b)
                if av is None:
                    any_missing = True
                else:
                    any_data = True
                    tc += av
                    td += bv or 0
                    any_prov = any_prov or (r["data_status"] == "provisional")
            if not any_data:
                tot, st = "<td>%s</td><td>%s</td>" % (MISS, MISS), '<span class="chip m">Missing</span>'
            else:
                tot = "<td><b>%s</b></td><td><b>%s</b></td>" % (n0(tc), n0(td))
                st = '<span class="chip w">Provisional</span>' if any_prov else '<span class="chip f">Settled</span>'
                if any_missing:
                    st = '<span class="chip m">Partly missing</span>'
            out.append('<tr class="%s"><th scope="row">%s</th>%s%s<td>%s</td></tr>' % (cls, fmt_day(day), cells, tot, st))
        return "".join(out)

    if locs:
        head1 = "".join('<th colspan="2" class="grp">%s</th>' % esc(t) for t in locs.values()) + '<th colspan="2" class="grp">All locations</th>'
        head2 = "".join("<th>Call clicks</th><th>Directions</th>" for _ in range(len(locs) + 1))
        gmb_table = ('<div class="scroll"><table><thead><tr><th rowspan="2">Day (Melbourne)</th>%s<th rowspan="2">Data</th></tr><tr>%s</tr></thead><tbody>%s</tbody></table></div>') % (head1, head2, gmb_rows(30))
    else:
        gmb_table = '<p class="empty">%s Google Business Profile data has not synced yet.</p>' % MISS

    def gmb_kpi(key):
        a, b = period_days(today, key)
        tc = td = 0
        have = tot = 0
        day = a
        while day <= b:
            for lid in locs:
                tot += 1
                r = gidx.get((day, lid))
                if r and r["data_available"] and r.get("call_clicks") is not None:
                    have += 1
                    tc += r["call_clicks"]
                    td += r["direction_requests"] or 0
            day += timedelta(days=1)
        if have == 0:
            return '<div class="kpis g2"><div class="kpi"><span class="l">GMB call clicks</span><span class="v">%s</span></div><div class="kpi"><span class="l">GMB directions</span><span class="v">%s</span></div></div>' % (MISS, MISS)
        sub = "" if have == tot else '<span class="s">%d of %d location-days available</span>' % (have, tot)
        return ('<div class="kpis g2"><div class="kpi"><span class="l">GMB call clicks</span><span class="v">%s</span>%s</div>'
                '<div class="kpi"><span class="l">GMB directions</span><span class="v">%s</span>%s</div></div>') % (n0(tc), sub, n0(td), sub)

    # ------------------------------------------------------------------ breakdowns (Nimbata's own origin / first-click fields)
    def agg(rows, keyf):
        g = OrderedDict()
        for c in rows:
            k = keyf(c)
            a = g.setdefault(k, dict(calls=0, repeat=0, lines={}))
            a["calls"] += 1
            a["repeat"] += 1 if c.get("repeat") else 0
            a["lines"][c.get("line")] = a["lines"].get(c.get("line"), 0) + 1
        return g

    def bd_table(rows, keyf, none_label, head):
        if not live:
            return '<p class="empty">%s</p>' % MISS
        g = agg(rows, keyf)
        items = sorted(((k, v) for k, v in g.items() if k is not None), key=lambda kv: -kv[1]["calls"])
        none = g.get(None)
        if not items and none is None:
            return '<p class="empty">No calls in this period.</p>'
        if not items:
            return '<p class="empty">%s for these %d call(s) — Nimbata did not supply this field.</p>' % (none_label, none["calls"])
        body = ""
        for k, v in items + ([(None, none)] if none else []):
            name = esc(k) if k is not None else '<span class="miss">%s</span>' % esc(none_label)
            body += '<tr><th scope="row">%s</th><td><b>%d</b></td>%s</tr>' % (name, v["calls"], "".join("<td>%d</td>" % v["lines"].get(ln, 0) for ln in LINES))
        return '<div class="scroll"><table class="small"><thead><tr><th>%s</th><th>Calls</th>%s</tr></thead><tbody>%s</tbody></table></div>' % (
            head, "".join('<th style="--c:%s" class="ldot">%s</th>' % (LCOL(ln), esc(ln)) for ln in LINES), body)

    def path_of(u):
        if not u:
            return None
        p = urlparse(u if "//" in u else "//" + u)
        s = (p.path or "/")
        return (p.netloc.replace("www.", "") + s)[:70] if p.netloc else s[:70]

    def origin_block(rows):
        if not live:
            return '<p class="empty">%s</p>' % MISS
        total = len(rows) or 1
        g = agg(rows, lambda c: c.get("origin") or "Website direct")
        body = ""
        for b in ORIGINS:
            v = g.get(b)
            n = v["calls"] if v else 0
            share = 100.0 * n / total if rows else 0
            body += '<tr class="%s"><th scope="row"><i class="dot" style="background:%s"></i>%s</th><td><b>%d</b></td>%s<td><div class="share" style="--c:%s"><i style="width:%.0f%%"></i><span>%.0f%%</span></div></td></tr>' % (
                "" if n else "zero", OCOL(b), esc(b), n, "".join("<td>%d</td>" % (v["lines"].get(ln, 0) if v else 0) for ln in LINES), OCOL(b), share, share)
        return '<div class="scroll"><table class="small"><thead><tr><th>Origin</th><th>Calls</th>%s<th>Share</th></tr></thead><tbody>%s</tbody></table></div>' % (
            "".join('<th style="--c:%s" class="ldot">%s</th>' % (LCOL(ln), esc(ln)) for ln in LINES), body)

    def pview(key, label, inner_fn):
        a, b = period_days(today, key)
        rows = [c for c in calls if c["_day"] and a <= c["_day"] <= b]
        return '<div class="pv" data-p="%s" hidden>%s</div>' % (key, inner_fn(rows))

    sections = {
        "source": "".join(pview(k, l, origin_block) for k, l in BREAK_PERIODS),
        "campaign": "".join(pview(k, l, lambda r: bd_table(r, lambda c: c.get("campaign"), "No campaign captured", "Campaign (first click)")) for k, l in BREAK_PERIODS),
        "keyword": "".join(pview(k, l, lambda r: bd_table(r, lambda c: c.get("keyword"), "No keyword captured", "Keyword")) for k, l in BREAK_PERIODS),
        "landing": "".join(pview(k, l, lambda r: bd_table(r, lambda c: path_of(c.get("landing_page")), "No landing page captured", "Landing page")) for k, l in BREAK_PERIODS),
    }

    # ------------------------------------------------------------------ recent calls
    def recent():
        if not live:
            return '<p class="empty">%s</p>' % MISS
        rows = sorted([c for c in calls if c["_dt"]], key=lambda c: c["_dt"], reverse=True)[:50]
        if not rows:
            return '<p class="empty">No calls yet.</p>'
        body = ""
        for c in rows:
            who = '<span class="chip w">Repeat</span>' if c.get("repeat") else ('<span class="chip f">New</span>' if c.get("first_time") else "—")
            body += ("<tr><th scope=\"row\">%s</th><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td title=\"%s\">%s</td><td>%s</td></tr>") % (
                esc(c["_dt"].strftime("%a %-d %b, %-I:%M %p")), '<span class="pill" style="--c:%s">%s</span>' % (LCOL(c.get("line")), esc(c.get("line") or "—")),
                '<span class="pill" style="--c:%s">%s</span>' % (OCOL(c.get("origin")), esc(c.get("origin") or "—")),
                esc(c.get("campaign") or "—"), esc(c.get("keyword") or "—"), esc(c.get("caller") or "—"),
                esc(c.get("landing_page") or ""), esc(path_of(c.get("landing_page")) or "—"), who)
        return ('<div class="scroll"><table class="small"><thead><tr><th>Date / time</th><th>Line</th><th>Origin</th><th>Campaign (first click)</th><th>Keyword</th>'
                '<th>Caller</th><th>Landing page</th><th>New / repeat</th></tr></thead><tbody>%s</tbody></table></div>') % body


    # ------------------------------------------------------------------ page
    tabs = "".join('<button type="button" data-tab="%s" aria-pressed="%s">%s</button>' % (k, "true" if k == "yesterday" else "false", l) for k, l in PERIODS)
    kpi_html = "".join('<div class="pv" data-p="%s" hidden>%s%s</div>' % (k, kpi_block(k), gmb_kpi(k) if k in ("yesterday", "last_7", "last_30") else "") for k, _ in PERIODS)
    btabs = "".join('<button type="button" data-btab="%s" aria-pressed="%s">%s</button>' % (k, "true" if k == "last_7" else "false", l) for k, l in BREAK_PERIODS)
    window = "Yesterday = %s (12:00 AM – 11:59:59 PM Melbourne)." % fmt_day(today - timedelta(days=1), True)

    css = CSS
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
           '<title>Call Tracking — Nimbata</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">'
           '<style>' + css + '</style></head><body><div class="wrap">'
           '<header class="hero"><div class="eyebrow">Call tracking</div><h1>Call Tracking — Nimbata</h1>'
           '<p class="sub">Number of calls on each Nimbata tracking number and where they came from, plus Google Business Profile call clicks and directions. Updated ' + esc(updated) + '. ' + esc(window) + '</p></header>'
           + banner +
           '<section class="panel" id="kpi-panel"><div class="bar"><div class="tabs" id="ptabs">' + tabs + '</div></div>' + kpi_html +
           '<p class="hint">GMB <b>call clicks</b> are taps on the Call button in Google, not completed calls — Nimbata counts the real calls.</p></section>'
           '<section class="panel"><h2>Calls per day — last 30 days</h2><p class="hint">Each bar is one Melbourne day, split by tracking number.</p>' + chart_html(30) + '</section>'
           '<section class="panel"><h2>Calls per day — by tracking number</h2><p class="hint">Melbourne calendar days. <b>Final</b> = reconciled with the Nimbata API; <b>Webhook only</b> = live feed, not yet API-verified; <b>Missing</b> = Nimbata was not connected. *<b>Direct dial</b> = people ringing your real number straight; Nimbata cannot see those, so they stay <b>Missing</b> until a phone call log is added.</p>'
           '<div class="tg"><button type="button" data-days="14" aria-pressed="true">14 days</button><button type="button" data-days="30" aria-pressed="false">30 days</button></div>' + nim_table + '</section>'
           '<section class="panel"><h2>Google Business Profile — day by day</h2><p class="hint">Call clicks and direction requests per location. Google publishes the latest 3–5 days late: a day Google has not reported shows <b>Missing</b> (not 0), and the days after it stay <b>Provisional</b> until settled.</p>' + gmb_table + '</section>'
           '<section class="panel" id="attr-panel"><div class="bar"><h2>Attribution breakdown</h2><div class="tabs" id="btabs">' + btabs + '</div></div>'
           '<h3>Origin (where the call came from)</h3>' + sections["source"] + '<h3>Campaign (first click)</h3>' + sections["campaign"] +
           '<h3>Keywords</h3>' + sections["keyword"] + '<h3>Landing pages</h3>' + sections["landing"] + '</section>'
           '<section class="panel"><h2>When people call</h2><p class="hint">Calls by hour of day (Melbourne), last 30 days.</p>' + hours_html() + '</section>'
           '<section class="panel"><h2>Recent calls</h2><p class="hint">Last 50 calls. Callers are masked to the last 3 digits.</p>' + recent() + '</section>'
           '<p class="foot">Source: Nimbata (webhook + API reconciliation) and Google Business Profile via Windsor, stored in Supabase. Origin and campaign use only the fields Nimbata captured (Google click ID, UTM, tracking source).</p>'
           '</div><script>' + JS + '</script></body></html>')

    # ------------------------------------------------------------------ tile summary for the hub
    y = summary.get("yesterday") or {}
    spark = [(daily[today - timedelta(days=i)]["calls"] if (today - timedelta(days=i)) in daily else 0) for i in range(14, 0, -1)]
    if live:
        yr = in_period("yesterday")
        stats = [[n0(len(yr)), "calls yesterday"], [n0(sum(1 for c in yr if c.get("line") == "Google Ads Paid")), "Google Ads yesterday"],
                 [n0(sum(1 for c in yr if c.get("line") in ("GMB SYD", "GMB MEL"))), "GMB yesterday"]]
    else:
        stats = [["—", "calls yesterday"], ["—", "Google Ads yesterday"], ["—", "GMB yesterday"]]
    meta = {"updated": updated, "stats": stats, "spark": [spark]}
    if not live:
        meta["warn"] = "Nimbata setup pending"
    elif any(fs.get(k, {}).get("ok") is False for k in ("nimbata", "gmb")):
        meta["warn"] = "A call-tracking sync failed — see report"
    return doc, meta


CSS = """
:root{--bg:#f6f4fa;--surface:#fff;--fg:#1d1729;--muted:#625a72;--line:#e3ddee;--accent:#0f766e;--on-accent:#fff;--cell:#f3eefc;
--up:#167a3f;--up-bg:#d6f0df;--down:#c0262d;--down-bg:#fbdcdc;--flat:#8a5d00;--flat-bg:#fbefcf;--info:#0550ae;--info-bg:#ddf4ff;
--display:"Fraunces",Georgia,serif;--body:"IBM Plex Sans",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1514;--surface:#172120;--fg:#eaf3f1;--muted:#9bb0ac;--line:#2a3a38;--accent:#5eead4;--on-accent:#06201c;--cell:#1f2c2a;
--up:#6ee7a0;--up-bg:#143824;--down:#ff8a90;--down-bg:#4b1e24;--flat:#f2cf65;--flat-bg:#453b13;--info:#79c0ff;--info-bg:#12304a}}
:root[data-theme="dark"]{--bg:#0f1514;--surface:#172120;--fg:#eaf3f1;--muted:#9bb0ac;--line:#2a3a38;--accent:#5eead4;--on-accent:#06201c;--cell:#1f2c2a;--up:#6ee7a0;--up-bg:#143824;--down:#ff8a90;--down-bg:#4b1e24;--flat:#f2cf65;--flat-bg:#453b13;--info:#79c0ff;--info-bg:#12304a}
*{box-sizing:border-box}html{color-scheme:light dark}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--body);font-size:16px;line-height:1.45;overflow-x:clip}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 56px;display:grid;gap:18px}.wrap>*{min-width:0}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
h1{font-family:var(--display);font-weight:600;font-size:clamp(28px,5.5vw,38px);line-height:1.1;margin:4px 0 6px;text-wrap:balance}
h2{font-family:var(--display);font-weight:600;font-size:22px;margin:0 0 6px}h3{font-size:14px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:20px 0 8px}
.sub,.hint,.foot{color:var(--muted);font-size:14px;margin:0 0 12px}.foot{font-size:13px;margin-top:6px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:12px}.bar h2{margin:0}
.tabs,.tg{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}.bar .tabs{margin:0}
button{font:600 14px var(--body);padding:7px 14px;border-radius:999px;border:1.5px solid var(--line);background:var(--surface);color:var(--fg);cursor:pointer}
button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px;margin-bottom:10px}.kpis.g2{grid-template-columns:repeat(2,minmax(0,1fr))}
.kpi{background:var(--cell);border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:grid;gap:3px;align-content:start}
.kpi .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.kpi .v{font-family:var(--mono);font-size:24px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.15}.kpi .s{font-size:12px;color:var(--muted)}
.kpi.tot{background:var(--accent);border-color:var(--accent)}.kpi.tot .l,.kpi.tot .v,.kpi.tot .s{color:var(--on-accent)}.meter{height:8px;background:var(--line);border-radius:5px;overflow:hidden;margin:3px 0}.meter i{display:block;height:100%;border-radius:5px}
.meter i.g{background:var(--up)}.meter i.a{background:#d99a00}.meter i.r{background:var(--down)}
.note{border-radius:10px;padding:10px 14px;font-size:14px;border:1px solid var(--line)}.note.info{background:var(--info-bg);color:var(--info)}.note.warn{background:var(--flat-bg);color:var(--flat);font-weight:600}.note.bad{background:var(--down-bg);color:var(--down)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:760px;font-variant-numeric:tabular-nums;font-size:14px}
th,td{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;vertical-align:middle}tbody tr:last-child>*{border-bottom:0}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--surface);z-index:1;border-right:1px solid var(--line);min-width:128px}
thead th{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600;background:var(--surface)}thead th.grp{text-align:center;border-bottom:1px solid var(--line)}
tbody th{font-weight:500}td small,th small{color:var(--muted);font-weight:400;display:block;font-size:12px}th small.tag{display:inline;margin-left:4px}
table.small{min-width:620px}table.small td:nth-child(n+2),table.small thead th:nth-child(n+2){text-align:right}
tr.zero>*{color:var(--muted)}tr.x30{display:none}body.d30 tr.x30{display:table-row}
.miss{display:inline-block;padding:2px 8px;border-radius:7px;background:var(--down-bg);color:var(--down);font:600 12.5px var(--mono)}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font:600 12px var(--mono)}.chip.f{background:var(--up-bg);color:var(--up)}.chip.p,.chip.w{background:var(--flat-bg);color:var(--flat)}.chip.m,.chip.r{background:var(--down-bg);color:var(--down)}
.fl{display:inline-block;margin-right:4px;padding:1px 6px;border-radius:5px;background:var(--info-bg);color:var(--info);font:600 11px var(--mono)}
.share{position:relative;height:18px;min-width:90px;background:var(--line);border-radius:5px;overflow:hidden}.share i{position:absolute;inset:0 auto 0 0;background:var(--accent);opacity:.35}.share span{position:relative;font:600 12px var(--mono);padding:0 6px;line-height:18px}
.empty{color:var(--muted);margin:6px 0}
.hero{background:linear-gradient(120deg,#0f766e 0%,#2563eb 45%,#ec4899 100%);color:#fff;border-radius:16px;padding:22px 20px;box-shadow:0 6px 24px -10px rgba(37,99,235,.55)}
.hero .eyebrow,.hero .sub{color:rgba(255,255,255,.9)}.hero h1{color:#fff;margin-bottom:4px}.hero .sub{margin:0}
.kpi{border-top:4px solid var(--c,var(--line));background:linear-gradient(180deg,color-mix(in srgb,var(--c,#888) 14%,var(--surface)),var(--surface) 85%)}
.kpi .v{color:var(--c)}.kpi.tot{background:linear-gradient(135deg,#0f766e,#2563eb);border-color:#0f766e;border-top-color:#5eead4}.kpi.tot .l,.kpi.tot .v,.kpi.tot .s,.kpi.tot .dl{color:#fff}
.dl{font:600 11.5px var(--mono)}.dl.up{color:var(--up)}.dl.dn{color:var(--down)}.dl.fl0{color:var(--muted)}
th.ldot{box-shadow:inset 0 -3px 0 var(--c);color:var(--fg)}
td.heat{background:color-mix(in srgb,var(--c) var(--p),transparent)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font:600 12px var(--body);color:var(--c);background:color-mix(in srgb,var(--c) 15%,var(--surface));border:1px solid color-mix(in srgb,var(--c) 40%,transparent)}
.share i{background:var(--c)!important;opacity:.55!important}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:0 0 10px;font-size:13px;color:var(--muted)}.lg i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px}
.chart{display:flex;gap:3px;align-items:flex-end;height:200px;padding:6px 2px 0;overflow-x:auto}
.col{flex:1 0 16px;min-width:16px;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.col .t{font:600 10.5px var(--mono);color:var(--muted);margin-bottom:2px;min-height:12px}
.col .stack{width:100%;max-width:26px;flex:1;display:flex;flex-direction:column-reverse;justify-content:flex-start;max-height:calc(100% - 32px);min-height:0}
.col .stack i{display:block;width:100%}
.col .x{font:500 10px var(--mono);color:var(--muted);margin-top:4px}.col.miss-col .stack{background:repeating-linear-gradient(45deg,var(--down-bg),var(--down-bg) 4px,transparent 4px,transparent 8px);flex:0 0 22px;border-radius:5px}
.hours{display:flex;gap:4px;align-items:flex-end;height:130px}.hc{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.hc i{display:block;width:100%;background:linear-gradient(180deg,#ec4899,#2563eb);border-radius:5px 5px 0 0;min-height:2px}.hc span{font:500 10px var(--mono);color:var(--muted);margin-top:4px;height:12px}
@media (max-width:640px){.wrap{padding:16px 12px 48px}}
"""

JS = """
(function(){
var P='yesterday',B='last_7';
function apply(){
  document.querySelectorAll('#ptabs button').forEach(function(b){b.setAttribute('aria-pressed',b.dataset.tab===P?'true':'false');});
  document.querySelectorAll('#btabs button').forEach(function(b){b.setAttribute('aria-pressed',b.dataset.btab===B?'true':'false');});
  document.querySelectorAll('#kpi-panel .pv').forEach(function(e){e.hidden=e.getAttribute('data-p')!==P;});
  document.querySelectorAll('#attr-panel .pv').forEach(function(e){e.hidden=e.getAttribute('data-p')!==B;});
}
document.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;
  if(b.dataset.tab){P=b.dataset.tab;apply();}
  else if(b.dataset.btab){B=b.dataset.btab;apply();}
  else if(b.dataset.days){document.body.classList.toggle('d30',b.dataset.days==='30');document.querySelectorAll('.tg button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});}
});
apply();
})();
"""


def main():
    src_path, out_html, out_meta = sys.argv[1:4]
    src = json.load(open(src_path))
    doc, meta = build(src)
    open(out_html, "w", encoding="utf-8").write(doc)
    json.dump(meta, open(out_meta, "w"), separators=(",", ":"))
    d = src["data"]
    print("Call tracking built for", d["today"], "| calls in window:", len(d["calls"]), "| gmb rows:", len(d["gmb_daily"]))


if __name__ == "__main__":
    main()
