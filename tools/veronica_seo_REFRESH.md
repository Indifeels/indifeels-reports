# Veronica · SEO (scheduled Claude tasks)

Two scheduled tasks run the skill `veronica-seo-agent` on the owner's computer (Claude in Chrome needed): daily light check Tue-Sun 7:43 am Melbourne, full run Monday 8:17 am (first full run Mon 30 Nov 2026).
Instructions: `tools/veronica_seo_SKILL.md`. Memory: Supabase `seo_agent_state`. Approvals: `cc_decisions` (bot `Veronica · SEO`, tag `approver`). Run log: `cc_bot_runs`.
Report: SEO Final (`seo-final`, see `tools/seo_final_REFRESH.md`). Never use the Semrush API. Never commit inputs or keys.
Open: Veronica's own hub login and access; Search Console access.

Owner notes: Decisions cards have Approve / Reject / Acknowledge (keep listed), a text box and a mic. Notes are saved in `cc_decisions.thread`; `awaiting` = 'agent' (needs review) or 'owner' (Veronica asked a question). Reviewed at the start of every run.
