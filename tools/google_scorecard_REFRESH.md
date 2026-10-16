# Google Scorecard refresh (`google-scorecard`)

Built by `tools/google_scorecard.py` from a JSON file of raw inputs. Template: `tools/google_scorecard_template.html` (all scoring and layout run in the page).
Inputs come from Windsor.ai and Shopify, so a Claude scheduled task collects them and runs the builder.
**Never commit the inputs file.** This repo is public; only the encrypted `r/google-scorecard.bin` and `r/google-scorecard.meta.bin` are committed.

## Steps
1. `git pull` main. Load the key from Supabase (project `yrigvovwyfpaybibfjva`): `select key_b64 from report_keys where report_id='google-scorecard'`. Export it as `GOOGLE_SCORECARD_KEY`. Do not print it or write it into the repo.
2. Collect the inputs below into `$SCRATCH/google-scorecard.json` (outside the repo).
3. `python3 tools/google_scorecard.py $SCRATCH/google-scorecard.json`
4. `git add r/google-scorecard.bin r/google-scorecard.meta.bin r/status.json`, commit "Refresh Google Scorecard", `git pull --rebase origin main`, push to `main` (retry up to 3 times).
5. If an input cannot be collected, do not publish partial data: `python3 tools/status.py r google-scorecard fail "short reason"`, commit `r/status.json` only, stop.

## Windows (Melbourne time)
Last 30 completed days ending yesterday for orders and daily Ads rows. Google Ads account `788-887-6041`. Tracked campaigns have "tracked" in the name; the non-tracked call/store campaign is code `D`.

## Inputs
| key | content |
|---|---|
| `meta` | `{refreshed, next, period, note, warn}` display strings |
| `orders` | online Shopify orders (`source_name:web`, amount > 0): `{n, t (UTC ISO), a (amount), m (custom.order_source code GW/FW/OO/RC/DO/UO/RS), js (customer journey source), us, um, uc (utm source/medium/campaign)}` |
| `qd` | per order (key = order number) from Supabase `order_attribution_queue` (joined by order name, `shopify_source='web'`): `{g: Shopify order gid, c: customer, src: order_source, sync, auto, mm: match method, note, utm{}, camp, adset, prod[], j:{first,last,moments[] (each {t,s,d,l,r,u}), days, idx, ready}}`. Only orders since the queue started (2 Oct 2026) have one. Without a `qd` entry the order's buttons stay browser-only. |
| `ids` | order name (no #) to Shopify numeric order id, for the admin links |
| `ads` | 30 days of daily campaign rows `{d, c (campaign code A-E), sp, imp, clk, conv, val, is, lb, lr}` (impression share, lost to budget, lost to rank) |
| `camps` | `{code: {name, type, id}}` |
| `life` | `{date: [tracked spend, conversions, conversion value]}` for every day since the first tracked spend (16 Apr 2026); tracked = name has "tracked" and not "non trac" |
| `cstat` | `{code: [status, daily budget]}` |
| `cact` | `[code, conversion action, conversions, value]` |
| `adgroups`, `ads_list` | Search ad groups and ads (spend, impressions, clicks, conversions, value, strength) |
| `kws` | paid keywords `[ad group, keyword, match type, spend, impr, clicks, conv, value]` |
| `stq` | paid search terms `{t, g, sp, imp, clk, cv, val}` |
| `gsc` | Search Console queries `[query, clicks, impressions, position]` (impressions 30+) |
| `ga4` | channel rows `{ch, s, e, atc, co, p, rev}` |
| `lp` | landing pages `{path, s, e, atc, p, rev}` |
| `gmb` | Business Profile `[{calls, dir, web} Melbourne, {calls, dir, web} Sydney]` |

Order buttons: inside the hub, Google / Facebook / Organic on a review order calls the `order-attribution` function (app.js handler for `scorecard-order-source`), which updates Shopify's `custom.order_source`; the choice then also shows here until the next refresh brings the new field value.

Not yet collected: Performance Max asset groups and search categories, Nimbata call matching, Merchant Center feed coverage, a monthly budget and targets. Those tiles show "–".
