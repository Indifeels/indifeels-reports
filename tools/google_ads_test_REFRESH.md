# Google Ads Test (`google-ads-test`)

Static page today: `tools/google_ads_test_template.html` via `tools/google_ads_test.py`. Setup progress is stored in the viewer's browser.
Planned: once TEST · Wedding PMax 01 is live, a Claude scheduled task (daily 7 am Melbourne) pulls yesterday's Google Ads data from Windsor.ai, fills the KPI/funnel tiles and the "what's going wrong" rows, and republishes. Recommendations only; changes are made by the owner.
Never commit raw inputs. This repo is public; only the encrypted `r/google-ads-test.bin` and `.meta.bin` are committed.
Key: Supabase `report_keys` where `report_id='google-ads-test'` (env `GOOGLE_ADS_TEST_KEY`).
