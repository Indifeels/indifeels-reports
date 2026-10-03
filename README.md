# Indifeels Reports

Installable web app for Indifeels performance reports.

- Sign-in, users and report permissions live in Supabase.
- Report files in `r/` are AES-256-GCM encrypted; keys are released only to signed-in users with access.
- Daily and Monthly reports refresh at 8:00 pm Australia/Sydney for the current-day preview and again at midnight for the completed-day final.
- Stock refreshes in real time after Shopify orders, with fallback checks at 7:00 am, 3:00 pm and 8:00 pm Australia/Sydney.
- Supabase report-outbox changes are checked by GitHub every 30 minutes.
- Order Attribution is event-driven from Shopify and syncs the selected `custom.order_source` value back to Shopify.
- Footwear SEO and Google Tracked currently require their own refresh pipelines; they are not covered by the Daily/Monthly schedule.
