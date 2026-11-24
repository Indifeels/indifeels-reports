# SEO Final refresh (manual, on request)

`SEO Final` (`seo-final`, admin-only, category SEO) is built by `tools/seo_final.py` from a JSON file of inputs.
**Never commit the inputs file.** This repo is public; only `r/seo-final.bin` and `r/seo-final.meta.bin` are committed.

## Steps
1. Key: Supabase project `yrigvovwyfpaybibfjva`, `select key_b64 from report_keys where report_id='seo-final'`. Export as `SEO_FINAL_KEY`. Never print it or write it into the repo.
2. Inputs (`DATA.json`, outside the repo):
   - `R`: per Semrush category `{vol, kw, ranked, avg}` from the Semrush UI exports (AU database; do not use the Semrush API). `KD`: volume-weighted keyword difficulty per category. `KW`: top 8 keywords per category `[keyword, volume, our position (0 = not ranking), difficulty]`.
   - `rows`: `[label, category, in-stock products, colour]` (stock from the live collection pages).
   - `have`: in-stock products per size 32-54 for each category; `tgt`: size targets (4, 15, 80, 100, 100, 100, 80, 50, 30, 20, 10, 10).
   - `pr`: price comparison (our median, Australian competitor medians, suggested range). `col`: % of in-stock products with the `custom.colour` metafield filled. `meta`: data dates.
3. `python3 tools/seo_final.py DATA.json` (writes `r/seo-final.bin`, `r/seo-final.meta.bin`, `r/status.json`). `--html OUT.html` gives a plain preview with no key.
4. Commit those three files, `git pull --rebase origin main`, push to `main`.
