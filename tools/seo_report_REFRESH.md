# SEO Report refresh (Mon and Thu, 6:00 am Melbourne)

The SEO Report (`seo-report`, admin-only, category SEO) is built by `tools/seo_report.py` from a JSON file of raw inputs.
The inputs come from Windsor.ai and Semrush, which only Claude can reach, so a Claude scheduled task collects them and runs the builder.
**Never commit the inputs file.** This repo is public; only the encrypted `r/seo-report.bin` and `r/seo-report.meta.bin` are committed.

## Steps
1. `git pull` main. Load the key from Supabase (project `yrigvovwyfpaybibfjva`): `select key_b64 from report_keys where report_id='seo-report'`. Export it as `SEO_REPORT_KEY`. Do not print it again or write it to a file in the repo.
2. Collect the inputs below into `$SCRATCH/seo-data.json` (outside the repo).
3. `python3 tools/seo_report.py $SCRATCH/seo-data.json` (writes `r/seo-report.bin`, `r/seo-report.meta.bin`, `r/status.json`).
4. `git add r/seo-report.bin r/seo-report.meta.bin r/status.json`, commit "Refresh SEO Report", `git pull --rebase origin main`, push to `main` (retry up to 3 times).
5. If any input cannot be collected, do not publish partial data. Run `python3 tools/status.py r seo-report fail "short reason"`, commit `r/status.json` only, and stop.

## Windows (today = run date, Melbourne)
- **GBP (Windsor `google_my_business`)**: last reliable day is 5 days before today (Google lags). Let `E` = that day. Current window = 23 days ending `E`; previous window = the 23 days before. `M_*` and `S_*` arrays hold 46 daily values, previous window first.
- **GSC (Windsor `searchconsole`, `sc-domain:indifeels.com`)**: 26-day windows ending 2 days ago; previous 26 days before.
- **GA4 (Windsor `googleanalytics4`)**: organic search = default channel group "Organic Search"; 56 daily values ending yesterday; first 28 = previous, last 28 = current.
- **Semrush**: project 12063566 (`indifeels.com`), database `au`, Position Tracking campaign `12063566_1034699`.

## Inputs (all required)
| key | content |
|---|---|
| `M_calls`, `M_dirs`, `M_web` | Melbourne daily call clicks, `direction_requests`, website clicks (46 values) |
| `S_calls`, `S_dirs`, `S_web` | same for Sydney |
| `M_imp`, `S_imp` | 23 daily `[mobile search, mobile maps, desktop search, desktop maps]` impressions, current window |
| `reviews` | `{"mel":{"n":total,"rating":avg,"new28":new in 28d},"syd":{...}}` |
| `indya` | `{"mel":N,"syd":N}` monthly GBP searches for the "indya" brand |
| `meta` | `{"gbp_start":"26 Aug","gbp_end":"10 Oct","audit_date":"14 Oct","ai_orders":0}` (labels for the windows and audit) |
| `g_clicks_prev/curr`, `g_imp_prev/curr`, `g_pos_prev/curr` | 26 daily GSC clicks, impressions, average position |
| `queries` | `[query, clicks, impressions, position]` for the top ~55 queries (impressions > 30) |
| `named_clicks` | total clicks over the 28-day window counted at query level |
| `pages_qw` | 5 `[path, clicks, impressions, position]` pages with the worst CTR / biggest title wins |
| `top_pages` | 6 `[path, clicks]` top pages by clicks |
| `sess`, `purch`, `rev` | 56 daily organic sessions, purchases, revenue |
| `channels` | `[channel, sessions, revenue]` 28 days (all default channel groups) |
| `landing_rev` | `[path, sessions, purchases, revenue]` organic landing pages with revenue; revenue must sum to the 28-day organic revenue |
| `no_sale` | `[path, sessions]` 4 busy organic pages with no sale |
| `sem_months`, `sem_traffic`, `sem_top3` | 12 months of Semrush est. organic traffic and top-3 keyword counts |
| `comp`, `indi_traffic` | `[domain, common keywords, keywords, est. traffic]` for 6 real competitors; Indifeels est. traffic |
| `pt` | Position Tracking: `{"tracked","top3","top3_d","top10","top10_d","vis"}` |
| `audit` | Site Audit snapshot: `pages, errors, warnings, notices, clean, redirected_pages, broken, flagged, err_types [[name,count]...], orphan_sm, deep, one_link, redirected, dup_pages, schema_found` |
| `onp` | `[name, count, weight]` for Missing meta description (1.0), Missing H1 (1.0), Multiple H1 (0.5), H1 same as title (0.5), Duplicate meta description (0.5), Title too short (0.5) |
| `sitemaps` | `[path, urls, errors, warnings, last read, "live"/"stale"]` from Search Console |
| `bl` | `{"domains","links","authority","follow","nofollow"}` from Semrush backlinks overview |
| `ads` | `[term, clicks, cost, conversions, organic position, organic clicks]` brand search terms in Google Ads (28 days) |
| `ai_sessions` | GA4 sessions from the "AI Assistant" channel, 28 days |
| `local_kw`, `total_kw`, `aio_kw` | Semrush domain overview: Local Pack keywords, organic keywords, AI Overview keywords |
| `fixlists` | `{"health":[...],"onpage":[...]}`; each group `{sev:"bad"/"warn", title, count, fix, items:[...]}`. Build from Site Audit `issue_details` (snapshot from `snapshots`, newest first) for ids 2, 8, 7, 15, 101, 12 (health) and 103, 106, 15 (onpage). Items are paths; broken-link items are `"/blog/path  →  /product/slug/"`. |

## Cost control (Semrush units)
- `issue_details` calls have reported 0 API units. `snapshots` and `meta_issues` cost 100 units each, so do not call `meta_issues` (ids are listed above) and call `snapshots` once per run.
- If any Semrush call reports a non-zero unit cost beyond that, or fails with a zero-balance error, stop and fail the status as in step 5.
- Do not run Position Tracking, Domain Overview or Backlinks reports more than once per run.
