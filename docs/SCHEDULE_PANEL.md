# Report Schedule Panel

The Schedule Panel is a native authenticated dashboard report. Admins can edit shared schedules; report access still follows the existing dashboard permissions. It uses the approved phone layout and muted lavender theme, with green completed, yellow in-progress, grey future/queued and red failed runs.

## Schedule authority

`public.report_refresh_control` stores per-report enable switches and runner ownership. `public.report_schedules` holds multiple time and event schedules. The `report-scheduler` Edge Function is called each minute by Supabase Cron with a private database token. It atomically claims due work, dispatches the registered GitHub workflow, and matches each result to its exact named dispatch. Failed or cancelled builds are red. Ordinary workflow/manual business actions remain available; legacy report generation crons have been removed.

All calendar schedules use Australia/Melbourne. Fortnightly is every 14 days from the start date. Monthly, quarterly and yearly schedules retain their anchor day, clamped to the last day of shorter months. Existing monitor/journey checks also use interval schedules. DST is resolved by PostgreSQL's Melbourne timezone rules. A skipped local clock time moves forward; an ambiguous clock time runs once.

New Shopify orders and upstream Supabase file syncs enqueue events. Trigger switches and individual trigger schedules determine which reports run. Repeated events within 2 minutes are coalesced while active work is protected from duplication. Only the last 2 terminal results per report are retained; the next 2 scheduled occurrences are calculated from saved schedules. Active runs remain visible separately.

The existing outbox delivery workflow remains an infrastructure transport. It no longer owns workflow-built Daily, Monthly or Google outputs, preventing older outbox copies from overwriting fresh builds.

## Known gap

SEO Rankings has no unattended GSC/rank collector registered in this repository. The panel flags it as not connected; creating a schedule will record a red failed attempt rather than fabricate fresh ranking data. Register a real collector workflow before assigning it as the SEO runner.

## Deployment and verification

Database schema: `supabase/report_schedules.sql`. Edge Function source: `supabase/functions/report-scheduler/index.ts`. Frontend: `schedule-panel.js` and `schedule-panel.css`, with the native route and tile in `app.js` / `index.html`. Asset versions and service worker cache must move together when deploying updates.

No report keys, GitHub tokens or scheduler secrets belong in public source. SQL RPC permissions restrict saving to existing admins and runner operations to the service role. The scheduler token is generated and held in the private database schema.
