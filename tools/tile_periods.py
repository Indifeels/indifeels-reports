"""Home-tile period stats embedded in each report page as hidden JSON: Spend, Revenue, ROAS or Messages, Profit
for Yesterday / 7 / 15 / 30 days / Lifetime. Profit = revenue after GST and product cost, minus ad spend."""
import json, datetime as dt
CONTRIB = 0.75 / 1.1
def money(v): return ("-" if v < 0 else "") + f"${abs(v):,.0f}"
def periods(end, spd, rvd, msd=None):
    out = {}
    wins = [("y", "Yesterday", 1), ("d7", "7 days", 7), ("d15", "15 days", 15), ("d30", "30 days", 30), ("life", "Lifetime", None)]
    for key, label, n in wins:
        ks = None if n is None else [(end - dt.timedelta(i)).isoformat() for i in range(n)]
        pick = (lambda d: sum(d.values())) if ks is None else (lambda d: sum(d.get(k, 0) for k in ks))
        s, r = pick(spd), pick(rvd)
        third = ([f"{int(round(pick(msd))):,}", "Messages"] if msd is not None else [f"{r/s:.2f}x" if s else "—", "ROAS"])
        out[key] = {"label": label, "stats": [[money(s), "Spend"], [money(r), "Revenue"], third, [money(r * CONTRIB - s), "Profit"]]}
    return out
def sums(*blocks):
    """Combine period blocks (all ROAS style) into one: sum spend, revenue and profit."""
    num = lambda t: float(t.replace("$", "").replace(",", ""))
    out = {}
    for k in blocks[0]:
        s = sum(num(b[k]["stats"][0][0]) for b in blocks); r = sum(num(b[k]["stats"][1][0]) for b in blocks); p = sum(num(b[k]["stats"][3][0]) for b in blocks)
        out[k] = {"label": blocks[0][k]["label"], "stats": [[money(s), "Spend"], [money(r), "Revenue"], [f"{r/s:.2f}x" if s else "—", "ROAS"], [money(p), "Profit"]]}
    return out
def tag(p): return '<script type="application/json" id="tile-periods">' + json.dumps(p).replace("</", "<\\/") + "</script>"
