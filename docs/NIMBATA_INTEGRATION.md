# Nimbata call tracking + Google Business Profile

Report: **Call Tracking — Nimbata** (`call-tracking`). Counts calls per Nimbata tracking number per day, where each call came from, plus Google Business Profile (GMB) call clicks and directions.

## Architecture
```
Nimbata "After Every Call" webhook ──► Edge Function nimbata-webhook ─┐
Nimbata API (8 PM / 6 AM reconcile) ──► Edge Function nimbata-sync ───┼─► nimbata_calls (UPSERT on nimbata_call_id)
Windsor google_my_business ──► tools/fetch_call_tracking.py ──────────┴─► gmb_daily
                                         │
GitHub Action call-tracking.yml ─► sync_get_call_tracking() ─► tools/call_tracking.py ─► encrypted r/call-tracking.bin
```
Backend (ingestion) and UI (`tools/call_tracking.py`) only meet at the RPC `sync_get_call_tracking`, so the report can be redesigned without touching ingestion.

## Supabase objects (project `indifeels-reports`)
- Tables (RLS on, no anon/authenticated access): `nimbata_calls`, `nimbata_lines`, `gmb_daily`, `integration_sync_runs`, `call_day_status`, `integration_config`.
- Functions: `nimbata_ingest`, `gmb_ingest`, `nimbata_line`, `nimbata_origin`, `nimbata_source_bucket`, `sync_put_gmb_daily`, `sync_get_call_tracking`, `sync_log_run`, `call_tracking_health`, `nimbata_mark_days`, `run_call_tracking_health_monitor`.
- Views: `nimbata_call_daily`, `nimbata_call_summary` (today_partial / yesterday / last_7 / last_30 / lifetime), `gmb_daily_report`.
- pg_cron `call-tracking-health-10m` keeps the `nimbata` and `gmb` rows of Tech Availability current. Nimbata shows **Setup pending** (not an outage) until the first call arrives.
- Edge Functions (verify_jwt off; custom token auth): `nimbata-webhook`, `nimbata-sync`. Source in `supabase/functions/`.

## Secrets (never in GitHub or the browser)
Supabase Edge Function secrets: `NIMBATA_API_TOKEN` (required for reconciliation), optional `NIMBATA_CUSTOMER_ID`, `NIMBATA_API_URL`, `NIMBATA_CALLS_PATH`, `NIMBATA_PARAM_FROM`, `NIMBATA_PARAM_TO`, `NIMBATA_AUTH_SCHEME`, `NIMBATA_RECHECK_DAYS` (default 2).
Webhook auth: only the SHA-256 of the webhook token is stored (`integration_config.nimbata_webhook_token_sha256`); the token travels as `?key=` in the webhook URL.
GitHub Actions uses the existing `WINDSOR_API_KEY` and `SYNC_READ_TOKEN`.

## Nimbata setup
Integrations → Webhook → trigger *After Every Call*, POST JSON, URL `https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/nimbata-webhook?key=<WEBHOOK_TOKEN>`; include Unique Call ID, Start Time, Caller ID, Tracking Number (+ friendly name), Destination Number, Call Duration, Call Frequency, Configured Tracking Source, UTM Source/Medium/Campaign/Term, Google Ads Click ID, Landing Page, Device Type, Tags, Value. Click **Test** — test payloads are quarantined (`is_test`) and never reach the report.
Delivery is best effort, so the API reconciliation is what makes totals reliable.

## Tracking numbers → lines
`nimbata_line()` maps each call to **Website / GMB SYD / GMB MEL / Google Ads Paid**: first by exact number in `nimbata_lines.tracking_digits`, then by `name_pattern`, then by words in the Nimbata tracking-number name or source (SYD, MEL, Ads/Paid, Web). Anything else = "Unmapped line" (shown, never hidden). Pin the exact numbers:
```sql
insert into nimbata_lines(line, tracking_digits) values ('Website','61XXXXXXXXX'), ('GMB SYD','61XXXXXXXXX'), ('GMB MEL','61XXXXXXXXX'), ('Google Ads Paid','61XXXXXXXXX');
```
`nimbata_origin()` derives Google paid / GMB paid / GMB organic / Google organic / Meta / Referral / Website direct from the line, `gclid`, `fbclid`, medium and source.

## Schedule and time zone
Same as the other reports: workflow `call-tracking.yml`, cron `0 9,10,19,20 * * *` with a Melbourne gate.
- **8 PM (20:00–20:45)**: `partial` — today so far.
- **6 AM (06:00–06:45)**: `final` — previous Melbourne calendar day 00:00:00–23:59:59 (plus `NIMBATA_RECHECK_DAYS` earlier days), then marked Final. Never a rolling 24 hours.
`call_date` is a generated column in Australia/Melbourne, so DST changes are handled by the database.

## Idempotency and reconciliation
UPSERT on `nimbata_call_id`; raw payload kept as JSONB. API-verified values are authoritative: a late webhook cannot overwrite them, and NULLs never wipe stored values. Re-running a window creates no duplicates.

## Missing vs zero
Missing = data not available (Nimbata not connected for that day; Google has not yet published a GMB day — all-zero rows are treated as unpublished). Zero = a real zero. GMB "call clicks" are button taps, not calls.
**Direct dials to the real business number never pass through Nimbata**, so they cannot be counted (the column shows Missing).

## Errors
Categories recorded in `integration_sync_runs` and shown on the report: `auth`, `rate_limit`, `api_failure`, `network`, `malformed_payload`, `webhook_auth`, `db_failure`. Missing `NIMBATA_API_TOKEN` is "not configured", not an outage. The last good report stays published if a run fails.

## Attribution for Google Ads / Shopify matching
`gclid`, source, medium, campaign, keyword, landing page, UTMs and caller E.164 are stored unchanged for future exact matching. No fuzzy attribution; no revenue is invented.

## Safe changes
- Report look: edit `tools/call_tracking.py` only.
- New field: add alias in `nimbata_normalize.ts` (both function folders), column + ingest, expose in `sync_get_call_tracking`.
- Verify the API endpoint: POST `nimbata-sync` with `{"mode":"probe"}` and header `x-sync-token`.
