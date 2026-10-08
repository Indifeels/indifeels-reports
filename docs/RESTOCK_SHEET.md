# Restock → Google Sheet

Confirm in the Restock report writes to the `restock_confirmations` table and, if configured, appends to the supplier Google Sheet.

1. Open the sheet → Extensions → Apps Script, paste the script below, set `TOKEN`, Deploy → New deployment → Web app (Execute as: Me, Access: Anyone).
2. In Supabase → Edge Functions → Secrets add `RESTOCK_SHEET_WEBHOOK` (the web app URL) and `RESTOCK_SHEET_TOKEN` (same token).

```js
const TOKEN = "CHANGE-ME";
function doPost(e) {
  const b = JSON.parse(e.postData.contents);
  if (b.token !== TOKEN) return ContentService.createTextOutput("denied");
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const at = Utilities.formatDate(new Date(), "Australia/Melbourne", "d MMM yyyy, HH:mm");
  const rows = b.items.map(i => [at, i.image ? '=IMAGE("' + i.image + '?width=200")' : "", i.product, i.variant, i.stock, i.qty, i.status, i.url || ""]);
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, 8).setValues(rows);
  return ContentService.createTextOutput("ok");
}
```

Columns: A Confirmed on, B Image, C Product, D Variant, E Current stock, F Qty to order, G Status, H Product link. The Confirm toast says "Confirmed (sheet transfer pending)" until both secrets are set.
