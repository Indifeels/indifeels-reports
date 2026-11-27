# SEO Final change tracker

The section is embedded in the existing encrypted SEO Final report. No new report or access grant is needed. Existing demand/stock data retains its own original dates.

## Private source and refresh

Supabase project `yrigvovwyfpaybibfjva`, `public.seo_agent_state`, key `seo_final_change_tracker`, contains the private JSON payload. Read it through the authorized Supabase connector, write it to a temporary file outside this public repository, and fetch `report_keys.key_b64` for `report_id='seo-final'` privately into `SEO_FINAL_KEY`.

Run `python3 tools/seo_change_tracker.py /private/payload.json`. It decrypts the current report, replaces only the marked tracker section, preserves the rest and encrypts both report and metadata. `--html /private/preview.html` renders a preview without publishing. Commit only the encrypted outputs and public code. Never commit the JSON payload, baseline rows, clear HTML or keys.

`seo_final.py` also accepts `SEO_CHANGE_TRACKER_DATA=/private/payload.json`. Without this optional input it preserves the previous encrypted tracker section during a normal keyed rebuild, preventing accidental loss.

The confirmed ChatGPT automation is `Automation_afd030fe36908191abdff5cc76322314`, Melbourne mornings around 08:00 on 4, 11, 18, 25 December 2026 and 1 January 2027 (the extra run allows complete 28-day data to settle). This is a scheduled agent review, not a GitHub cron or Schedule Panel runner. Schedule dates are appointments, not evidence of successful data retrieval. After the final run mark it completed, with no next check; do not imply monitoring continues.

## Measurement and data contract

Retain the 11 labels already in SEO Final: Sarees, Lehenga, Suits, Salwar · Palazzo, Men Kurta, Kurti, Anarkali, Footwear, Kids, Jewellery, Wedding · Bridal. Membership is the saved Shopify collection handles, not title keyword guesses. Refresh from Shopify before making new eligibility decisions. The initial catalogue is 26 Nov 2026, with suits overlaid from the verified 27 Nov tracker. Stock and memberships are dated snapshots.

`categories[]` contains `label,total,inStock,published,metadataOnly,protected,pending,excluded,previous,baseline,changedBaseline,after,details`. `details[]` contains product ID, title, URL, recorded changes with field/publication/verification and optional before/after text, and separate indexing request, indexed status, last crawl, recrawl-after-publication and content-adoption evidence. Missing evidence stays unknown. `periods` holds exact inclusive windows; metrics contain clicks, impressions, CTR, impression-weighted position and returnedPages. Preserve baselines; add dated follow-up metrics and their windows, rather than overwriting pre-change values. `after` can include `start,end` and separate `changedProducts` metrics. Set each category's `nextCheck` from the actual remaining automation runs.

Published counts any unique product with a verified or recorded published change in the supplied logs; it does not mean fully researched/optimised. Pending is in-stock, unprotected and without a recorded edit, and is a review queue, not permission for bulk edits. Protected counts only in-stock products; unavailable counts all remaining products. Published products may later become unavailable/protected, so these status counts overlap. Metadata-only and content edits must remain distinguishable. Exact suits before/after and rollback remain in Library `libfile_1539b571cba88191ad35201e09d885a9` and backup `libfile_71db1122c26c8191aeb8198ca844d275`; previous pilots are in `seo_change_log` / `seo_content_snapshots`.

Use Windsor Search Console page/date/country rows for Australia, all devices, web search, complete dates. Initial equal 7-day windows: 11–17 Nov and 18–24 Nov 2026. These precede 26–27 Nov edits. Collection-page traffic is excluded from product totals. Categories overlap; don't sum them. Missing page/query rows are not proof of zero visibility or failed indexing. Compare complete 7/14/28-day post-publication windows against equal pre-publication windows; reporting delay can leave a due review waiting for data. Use query rows for target-keyword movement when mapped; page position is not a target keyword rank. Account for stock, seasonality and other edits before interpreting movement.

Google indexing requests have not been submitted by this task. Windsor exposes no Search Console write actions. Use authorized URL Inspection if available to record indexing and last-crawl evidence; manual Request Indexing may be needed, but normal recrawling may also pick up changes. A last-crawl timestamp after publication does not prove Google adopted the new content. The restricted Indexing API is not for ordinary product pages: https://developers.google.com/search/apis/indexing-api/v3/using-api

## Validation

Before publication: verify all 11 categories, no duplicated section on repeat runs, HTML escaping, encrypted read-back, baseline arithmetic, dates/filters, and schedule state. Verify main branch and deployment after publishing. No Shopify product content is modified by this reporting workflow.
