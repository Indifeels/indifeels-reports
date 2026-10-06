"""Build the Order Source report (sales, ROAS and profit by source) from fetched inputs.

Usage: order_source.py DATA.json OUT.html OUT.meta.json

DATA.json comes from tools/fetch_order_source.py. All calculation happens here.

Business rules (agreed with the owner):
  Facebook tracked      = FB Online Orders - WEB                      + tracked Meta campaigns
  Facebook non-tracked  = FB WHATSAPP / FB-IG PAGE MSGS / FB CALLS    + non-tracked Meta campaigns
  Google tracked        = Google Online Orders - WEB                  + tracked Google campaigns
  Google non-tracked    = Google Ads share of "Google Direction MEL - Store Visit" + non-tracked Google campaigns
  Organic               = Organic Orders, Google CALLS (GMB), Referral SEO etc, GMB share of store visits, SEO cost
  No-spend              = Marketplace, Word of Mouth, Direct order, Repeat Customer, unassigned
  Store visits are split by direction counts (Google Ads vs GMB) using the 30-day ratio for every period.
  Fixed costs per day (monthly / 30): Google mgmt $670, Facebook mgmt 15,000 INR / 67, organic/SEO $250.
  Platform fees are split between tracked and non-tracked by ad spend.
  Profit = revenue / 1.1 (GST) x 0.75 (after 25% product cost) - ad spend - fees.   ROAS = revenue / spend.
Periods use complete Melbourne days only (today is excluded).
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Melbourne")
HERE = os.path.dirname(os.path.abspath(__file__))
PERIODS = [("y", 1), ("d7", 7), ("d15", 15), ("d30", 30)]
FEE = {"g": 670 / 30, "f": 15000 / 67 / 30, "o": 250 / 30}
FALLBACK_ADS_SHARE = 232 / 384  # used only if a directions source is unavailable
GST, KEEP = 1.1, 0.75


def pd(s):
    return date.fromisoformat(str(s)[:10])


def fmt_d(d):
    return d.strftime("%-d %b")


def build(src):
    end = pd(src["end"])
    windows = {k: (end - timedelta(days=n - 1), end) for k, n in PERIODS}
    windows["p30"] = (end - timedelta(days=59), end - timedelta(days=30))

    # ---- orders by order_source per period: {source: [orders, amount]}
    rows = []
    for o in src["orders"]:
        d = datetime.fromisoformat(o["created"].replace("Z", "+00:00")).astimezone(TZ).date()
        rows.append((d, float(o["amount"]), o["source"] or "(Untagged)"))
    data = {}
    for k, (a, b) in windows.items():
        agg = defaultdict(lambda: [0, 0.0])
        for d, amt, s in rows:
            if a <= d <= b:
                agg[s][0] += 1
                agg[s][1] += amt
        data[k] = {s: [c, round(t, 2)] for s, (c, t) in agg.items()}

    # ---- campaign spend per period
    def spend(rows_, k):
        a, b = windows[k]
        agg = defaultdict(float)
        for r in rows_:
            if a <= pd(r["date"]) <= b:
                agg[r["campaign"] or "(no name)"] += float(r["spend"] or 0)
        return {c: v for c, v in agg.items() if v > 0}

    FB = {k: spend(src["fb"], k) for k, _ in PERIODS}
    G = {k: spend(src["google"], k) for k, _ in PERIODS}

    # ---- store-visit split (Google Ads vs GMB), 30-day ratio
    a30, b30 = windows["d30"]
    note_dirs = ""
    if src.get("ads_dirs") is not None and src.get("gmb_dirs") is not None:
        ads = sum(float(r["n"]) for r in src["ads_dirs"] if a30 <= pd(r["date"]) <= b30)
        gmb = sum(float(r["n"]) for r in src["gmb_dirs"] if a30 <= pd(r["date"]) <= b30)
        ads_share = ads / (ads + gmb) if (ads + gmb) > 0 else FALLBACK_ADS_SHARE
        if ads + gmb <= 0:
            note_dirs = "Direction counts were empty, so the stored 60/40 split was used for store visits."
    else:
        ads_share = FALLBACK_ADS_SHARE
        note_dirs = "Direction counts were unavailable, so the stored 60/40 split was used for store visits."

    unflagged = []

    def cls(n):
        l = n.lower()
        if l.startswith("tracked"):
            return "t"
        if "non trac" in l:
            return "n"
        unflagged.append(n)
        return "n"  # kept in non-tracked so spend is never dropped; flagged on the page

    def N(name, spend_=None, revenue=None, orders=None, kids=None, note=None):
        if kids:
            sp = [k["spend"] for k in kids if k["spend"] is not None]
            rv = [k["revenue"] for k in kids if k["revenue"] is not None]
            spend_ = sum(sp) if sp else None
            revenue = sum(rv) if rv else None
            orders = sum(k["orders"] or 0 for k in kids) if rv else None
        roas = (revenue / spend_) if (spend_ and revenue is not None) else None
        d = {"name": name, "spend": spend_, "revenue": revenue, "orders": orders, "roas": roas, "note": note, "profit": None}
        if kids:
            d["kids"] = kids
        return d

    def profit(n):
        if n.get("revenue") is None:
            return
        n["profit"] = n["revenue"] / GST * KEEP - (n["spend"] or 0)

    def sv(p, name, label=None, mult=1.0, note=None):
        c, a = data[p].get(name, [0, 0.0])
        return N(label or name, revenue=a * mult, orders=c * mult, note=note)

    model = {}
    for p, days in PERIODS:
        def platform(camps, key, tr_src, nt_src, label):
            t = [N(c, v) for c, v in sorted(camps.items()) if cls(c) == "t"]
            n = [N(c, v) for c, v in sorted(camps.items()) if cls(c) == "n"]
            st = sum(k["spend"] for k in t)
            sn = sum(k["spend"] for k in n)
            tot = (st + sn) or 1
            fee = FEE[key] * days
            t.append(N("Management fee share", fee * st / tot))
            n.append(N("Management fee share", fee * sn / tot))
            tn = N(label + " tracked", kids=t + tr_src)
            nn = N(label + " non-tracked", kids=n + nt_src)
            profit(tn)
            profit(nn)
            # group campaign rows into one collapsible "Ad campaigns (n)" row when there are several
            for node in (tn, nn):
                camps_ = [k for k in node["kids"] if k["revenue"] is None and k["name"] != "Management fee share" and "kids" not in k and k["spend"] is not None]
                if len(camps_) >= 2:
                    rest = [k for k in node["kids"] if k not in camps_]
                    node["kids"] = [N("Ad campaigns (%d)" % len(camps_), sum(c["spend"] for c in camps_), kids=None)] + rest
                    node["kids"][0]["kids"] = camps_
            g = N(label, kids=[tn, nn])
            profit(g)
            return g

        store = data[p].get("Google Direction MEL - Store Visit", [0, 0.0])
        google = platform(G[p], "g", [sv(p, "Google Online Orders - WEB")],
                          [N("Store visits (Google Ads share %d%%)" % round(ads_share * 100), revenue=store[1] * ads_share,
                             orders=store[0] * ads_share, note="Directions split GMB vs Google Ads, 30-day ratio")], "Google")
        fb = platform(FB[p], "f", [sv(p, "FB Online Orders - WEB")],
                      [sv(p, "FB WHATSAPP MSGS MEL - SALE"), sv(p, "FB/IG PAGE MSGS MEL - SALE"), sv(p, "FB CALLS MEL - SALE")], "Facebook")
        org = N("Organic", kids=[sv(p, "Organic Orders"), sv(p, "Google CALLS MEL - SALE", "Google calls (GMB)"), sv(p, "Referral SEO etc"),
                                 N("Store visits (GMB share %d%%)" % round((1 - ads_share) * 100), revenue=store[1] * (1 - ads_share),
                                   orders=store[0] * (1 - ads_share), note="Directions split GMB vs Google Ads, 30-day ratio"),
                                 N("SEO / organic cost", FEE["o"] * days)])
        profit(org)
        nos = N("No-spend sources", kids=[sv(p, "Marketplace MEL"), sv(p, "Word of Mouth"), sv(p, "Direct order"),
                                          sv(p, "Repeat Customer"), sv(p, "(Untagged)", "Unassigned (no source)")])
        profit(nos)
        for k_ in nos["kids"]:
            profit(k_)  # no ad cost on these sources, so each shows profit after product cost and GST
        paid = N("Total with spend", kids=[google, fb, org])
        profit(paid)
        paid.pop("kids")
        # Anything in the order data that no group above claims must still reach the totals (never silently dropped).
        known = {"Google Online Orders - WEB", "Google Direction MEL - Store Visit", "FB Online Orders - WEB", "FB WHATSAPP MSGS MEL - SALE",
                 "FB/IG PAGE MSGS MEL - SALE", "FB CALLS MEL - SALE", "Organic Orders", "Google CALLS MEL - SALE", "Referral SEO etc",
                 "Marketplace MEL", "Word of Mouth", "Direct order", "Repeat Customer", "(Untagged)"}
        extra = {s: v for s, v in data[p].items() if s not in known}
        if extra:
            nos["kids"] += [N(s + " (not in a group)", revenue=v[1], orders=v[0]) for s, v in sorted(extra.items())]
            nos["revenue"] = (nos["revenue"] or 0) + sum(v[1] for v in extra.values())
            nos["orders"] = (nos["orders"] or 0) + sum(v[0] for v in extra.values())
            profit(nos)
        allr = (paid["revenue"] or 0) + (nos["revenue"] or 0)
        allt = {"name": "Total, all sources", "spend": paid["spend"], "revenue": allr,
                "orders": (paid["orders"] or 0) + (nos["orders"] or 0), "profit": (paid["profit"] or 0) + (nos["profit"] or 0),
                "roas": (allr / paid["spend"]) if paid["spend"] else None}
        # the page lists No-spend as the last group beside Google, Facebook and Organic
        model[p] = {"groups": [google, fb, org, nos], "paid": paid, "all": allt}

    camps_30 = set(FB["d30"]) | set(G["d30"])
    return dict(data=data, model=model, unflagged=sorted(set(unflagged)), ncamp=len(camps_30), ads_share=ads_share,
                note_dirs=note_dirs, windows=windows, end=end)


def main():
    src_path, out_html, out_meta = sys.argv[1:4]
    src = json.load(open(src_path))
    r = build(src)
    w = r["windows"]
    d = r["data"]
    ads = round(r["ads_share"] * 100)
    t = open(os.path.join(HERE, "order_source_template.html"), encoding="utf-8").read()
    windows_txt = ("Yesterday = %s · 7 days = %s – %s · 15 days = %s – %s · 30 days = %s – %s"
                   % (fmt_d(w["y"][0]), fmt_d(w["d7"][0]), fmt_d(w["d7"][1]), fmt_d(w["d15"][0]), fmt_d(w["d15"][1]),
                      fmt_d(w["d30"][0]), fmt_d(w["d30"][1])))
    if r["note_dirs"]:
        windows_txt += ". " + r["note_dirs"]
    model_json = json.dumps({"model": r["model"], "unflagged": r["unflagged"], "ncamp": r["ncamp"]})
    # "</" inside inline JSON must not close the script tag
    model_json = model_json.replace("</", "<\\/")
    data_json = json.dumps(d).replace("</", "<\\/")
    for key, val in (("__DATA__", data_json), ("__MODEL__", model_json), ("__PREV__", "%s – %s" % (fmt_d(w["p30"][0]), fmt_d(w["p30"][1]))),
                     ("__WINDOWS__", windows_txt), ("__ADS__", str(ads)), ("__GMB__", str(100 - ads))):
        assert key in t, "template placeholder missing: " + key
        t = t.replace(key, val)
    for left in ("__DATA__", "__MODEL__", "__PREV__", "__WINDOWS__", "__ADS__", "__GMB__"):
        assert left not in t
    # sanity: every order in the 30-day window reaches the all-sources total
    tot30 = sum(v[1] for v in d["d30"].values())
    assert abs(tot30 - r["model"]["d30"]["all"]["revenue"]) < 0.5, "revenue does not reconcile to Shopify"
    open(out_html, "w", encoding="utf-8").write(t)

    y = r["model"]["y"]["paid"]
    ya = r["model"]["y"]["all"]  # tile covers ALL sources; ROAS = all revenue / ad spend
    money = lambda v: ("−" if v < 0 else "") + "${:,.0f}".format(abs(v))
    meta = {
        "updated": datetime.fromisoformat(src["now"]).astimezone(TZ).strftime("%-d %b %Y, %-I:%M %p"),
        "stats": [[money(y["spend"] or 0), "spend yesterday"],
                  [money(ya["revenue"] or 0), "revenue yesterday"],
                  ["%.2fx" % ya["roas"] if ya["roas"] is not None else "—", "overall ROAS yesterday"],
                  [money(ya["profit"] or 0) + (" (%d%%)" % round(ya["profit"] / ya["revenue"] * 100) if ya["revenue"] else ""), "profit yesterday"]],
    }
    if r["unflagged"]:
        meta["warn"] = "%d campaign(s) missing Tracked / Non Tracked" % len(r["unflagged"])
    json.dump(meta, open(out_meta, "w"), separators=(",", ":"))
    print("Order Source built through", r["end"], "| yesterday spend", round(y["spend"] or 0, 2), "revenue", round(y["revenue"] or 0, 2),
          "ROAS", None if y["roas"] is None else round(y["roas"], 2), "profit", round(y["profit"] or 0, 2), "| unflagged:", r["unflagged"])


if __name__ == "__main__":
    main()
