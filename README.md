# Indifeels Reports

Installable web app for Indifeels performance reports.

- Sign-in, users and report permissions live in Supabase.
- Report files in `r/` are AES-256-GCM encrypted; keys are released only to signed-in users with access.
- Reports are rebuilt and published every night at 10 pm Sydney time.
