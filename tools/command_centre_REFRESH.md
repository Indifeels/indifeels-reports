# Master Dashboard (`command-centre`)

Static page today: `tools/command_centre_template.html` via `tools/command_centre.py`. Scores and alerts in the page are sample values.
Planned: each live report feeds its own score and alert into the matching tile, then the page is republished.
Admin-only. Top section "Command Centre" in the hub. "Open this report" buttons message the hub (`cc-open`), which opens the matching report.
This repo is public; only the encrypted `r/command-centre.bin` and `.meta.bin` are committed.
Key: Supabase `report_keys` where `report_id='command-centre'` (env `COMMAND_CENTRE_KEY`). Never print it or write it to a file.
