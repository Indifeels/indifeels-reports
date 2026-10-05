# Indifeels Reports

Installable web app for IndiFeels performance reports.

## Operating model

- **Code/Claude owns report design and logic.** New templates, calculations, parameters and report definitions are pushed to GitHub `main`.
- **GitHub `main` is the single source of truth.** Scheduled refresh jobs always check out the current branch before fetching data and building reports.
- **`reports-manifest.json` is the report contract.** A new report must be registered there with its outputs, builders, schedule/owner and required configuration.
- **Refreshes validate before publishing.** `tools/report_preflight.py` checks the manifest and required configuration before a build, then validates expected outputs before a commit.
- **Last good output is preserved on build failure.** Failed jobs record status instead of intentionally publishing incomplete report files.
- **Publishing is collision-safe.** Each report keeps its own concurrency group so simultaneous 8 PM jobs are not cancelled; publish steps use pull/rebase/retry to absorb newer commits pushed while a refresh is running.
- **Refresh status records the code version.** `r/status.json` includes the Git commit SHA, manifest version and report data cutoff where available.

## Current schedules

- Daily and Monthly: 8:00 PM Australia/Melbourne current-day preview; 6:00 AM final for the previous completed day.
- Google Tracked: 8:00 PM preview; 6:00 AM previous-day final.
- Stock / attribution: event-driven after Shopify orders, with 7:00 AM, 3:00 PM and 8:00 PM checks.
- Product Visibility: 7:00 AM, 3:00 PM and 8:00 PM.
- Supabase outbox sync: every 30 minutes, but only for report files explicitly marked `supabase_sync: true` in the manifest.
- Order Attribution: event-driven from Shopify and syncs the selected `custom.order_source` value back to Shopify.
- Tech Availability: maintained in Supabase by its monitoring function.

## Security

- Report files in `r/` are AES-256-GCM encrypted where applicable; report keys are released only to signed-in users with access.
- Secrets remain in GitHub/Supabase configuration and are not stored in `reports-manifest.json`.
- If Code introduces a new secret or credential requirement, add its environment-variable name to the manifest and wire the secret into the owning workflow before the next refresh. Preflight will fail closed if it is missing.
