// nimbata-sync — Nimbata API reconciliation (idempotent UPSERT on nimbata_call_id; API version is authoritative).
// Called by the GitHub "Refresh Call Tracking" workflow at 8 PM (mode "partial") and 6 AM (mode "final").
// Auth: header x-sync-token = the existing SYNC_READ_TOKEN (checked against sync.tokens by sync_check_token).
//
// Body: { mode: "final" | "partial" | "range" | "probe", from?: "YYYY-MM-DD", to?: "YYYY-MM-DD", recheck_days?: number }
//   final   : previous Melbourne calendar day (00:00:00–23:59:59), plus NIMBATA_RECHECK_DAYS earlier days. Marks days final.
//   partial : today so far (Melbourne). Marks today partial.
//   range   : explicit from/to (backfill / manual recheck).
//   probe   : one API request; returns HTTP status + response key names only (used to verify the endpoint).
//
// Secrets (Supabase Edge Function secrets — never in GitHub or the browser):
//   NIMBATA_API_TOKEN     required  Personal Auth Token
//   NIMBATA_CUSTOMER_ID   optional  sent as header X-Customer-Id and query customer_id when set
//   NIMBATA_API_URL       optional  default https://api.nimbata.com
//   NIMBATA_CALLS_PATH    optional  default /v1/calls
//   NIMBATA_PARAM_FROM / NIMBATA_PARAM_TO   optional query parameter names (default from / to)
//   NIMBATA_AUTH_SCHEME   optional  "Bearer" (default) or "Token"
//   NIMBATA_RECHECK_DAYS  optional  extra earlier days re-reconciled by the 6 AM run (default 2)
import { normalise, melbourneToday, addDays, callDayMelbourne, melbourneToUtc, safeFieldList } from "./nimbata_normalize.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const H = { apikey: SERVICE_KEY, Authorization: "Bearer " + SERVICE_KEY, "Content-Type": "application/json" };
const env = (k: string, d = "") => (Deno.env.get(k) || d).trim();

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

class SyncError extends Error { constructor(public category: string, msg: string) { super(msg); } }

async function rpc(fn: string, args: unknown) {
  const r = await fetch(SUPABASE_URL + "/rest/v1/rpc/" + fn, { method: "POST", headers: H, body: JSON.stringify(args) });
  if (!r.ok) throw new SyncError("db_failure", fn + " HTTP " + r.status + ": " + (await r.text()).slice(0, 160));
  const t = await r.text();
  return t ? JSON.parse(t) : null;
}

async function logRun(o: Record<string, unknown>) {
  try {
    await fetch(SUPABASE_URL + "/rest/v1/integration_sync_runs", {
      method: "POST", headers: { ...H, Prefer: "return=minimal" },
      body: JSON.stringify({ integration: "nimbata", run_type: "api_reconciliation", finished_at: new Date().toISOString(), ...o }),
    });
  } catch (_) { /* never mask the real result */ }
}

function scrub(s: string): string {
  const tok = env("NIMBATA_API_TOKEN");
  return tok ? s.split(tok).join("***") : s;
}

async function apiGet(u: URL): Promise<any> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: env("NIMBATA_AUTH_SCHEME", "Bearer") + " " + env("NIMBATA_API_TOKEN"),
  };
  if (env("NIMBATA_CUSTOMER_ID")) headers["X-Customer-Id"] = env("NIMBATA_CUSTOMER_ID");
  let last: SyncError | null = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    let r: Response;
    try {
      const ac = new AbortController(); const t = setTimeout(() => ac.abort(), 25000);
      r = await fetch(u, { headers, signal: ac.signal }); clearTimeout(t);
    } catch (e) {
      last = new SyncError("network", "network error: " + scrub((e as Error).message).slice(0, 120));
      await new Promise((ok) => setTimeout(ok, 1500 * (attempt + 1))); continue;
    }
    if (r.status === 401 || r.status === 403) throw new SyncError("auth", "Nimbata rejected the token (HTTP " + r.status + ")");
    if (r.status === 429) {
      last = new SyncError("rate_limit", "Nimbata rate limit (HTTP 429)");
      const ra = Number(r.headers.get("retry-after")) || 5 * (attempt + 1);
      await new Promise((ok) => setTimeout(ok, Math.min(ra, 30) * 1000)); continue;
    }
    if (r.status >= 500) { last = new SyncError("api_failure", "Nimbata API error HTTP " + r.status); await new Promise((ok) => setTimeout(ok, 2000 * (attempt + 1))); continue; }
    if (!r.ok) throw new SyncError("api_failure", "Nimbata API HTTP " + r.status + ": " + scrub((await r.text()).slice(0, 160)));
    try { return await r.json(); } catch (_) { throw new SyncError("malformed_payload", "Nimbata API returned non-JSON"); }
  }
  throw last || new SyncError("api_failure", "Nimbata API failed");
}

function rowsOf(x: any): any[] {
  if (Array.isArray(x)) return x;
  for (const k of ["data", "calls", "items", "results", "records", "rows"]) {
    if (Array.isArray(x?.[k])) return x[k];
    if (Array.isArray(x?.[k]?.data)) return x[k].data;
  }
  return [];
}

function nextOf(x: any, page: number): { url?: string; page?: number } | null {
  const link = x?.links?.next || x?.next || x?.next_page_url || x?.meta?.next || x?.pagination?.next;
  if (typeof link === "string" && /^https?:/.test(link)) return { url: link };
  const last = Number(x?.meta?.last_page ?? x?.last_page ?? x?.total_pages ?? x?.pagination?.total_pages ?? x?.meta?.total_pages);
  if (Number.isFinite(last) && page < last) return { page: page + 1 };
  if (x?.has_more === true || x?.meta?.has_more === true) return { page: page + 1 };
  return null;
}

function windowUrl(from: string, to: string, page: number): URL {
  const u = new URL(env("NIMBATA_CALLS_PATH", "/v1/calls"), env("NIMBATA_API_URL", "https://api.nimbata.com"));
  const [fy, fm, fd] = from.split("-").map(Number); const [ty, tm, td] = to.split("-").map(Number);
  // Melbourne calendar-day boundaries converted to UTC instants: 00:00:00 → 23:59:59 local, never a rolling 24 h.
  u.searchParams.set(env("NIMBATA_PARAM_FROM", "from"), melbourneToUtc(fy, fm, fd, 0, 0, 0));
  u.searchParams.set(env("NIMBATA_PARAM_TO", "to"), melbourneToUtc(ty, tm, td, 23, 59, 59));
  if (env("NIMBATA_CUSTOMER_ID")) u.searchParams.set("customer_id", env("NIMBATA_CUSTOMER_ID"));
  if (page > 1) u.searchParams.set("page", String(page));
  return u;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json(405, { ok: false, error: "method not allowed" });
  const ok = await rpc("sync_check_token", { p_token: req.headers.get("x-sync-token") || "" }).catch(() => false);
  if (ok !== true) return json(401, { ok: false, error: "unauthorized" });

  const body = await req.json().catch(() => ({}));
  const mode = String(body.mode || "final");
  const today = melbourneToday(); const yesterday = addDays(today, -1);
  let from = today, to = today;
  if (mode === "final") { const re = Number(body.recheck_days ?? env("NIMBATA_RECHECK_DAYS", "2")) || 0; from = addDays(yesterday, -Math.max(0, Math.min(re, 14))); to = yesterday; }
  else if (mode === "range") { from = String(body.from || ""); to = String(body.to || body.from || ""); }
  else if (mode === "probe") { from = yesterday; to = yesterday; }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to) || from > to) return json(400, { ok: false, error: "bad window" });

  if (!env("NIMBATA_API_TOKEN")) {
    await logRun({ status: "not_configured", window_from: from, window_to: to, detail: "NIMBATA_API_TOKEN secret not set; webhook data only" });
    return json(200, { ok: true, configured: false, mode, from, to, note: "NIMBATA_API_TOKEN not set — reconciliation skipped (not an outage)" });
  }

  try {
    if (mode === "probe") {
      const x = await apiGet(windowUrl(from, to, 1));
      const rs = rowsOf(x);
      return json(200, { ok: true, top_level_keys: Object.keys(x || {}).slice(0, 30), rows: rs.length,
        first_row_keys: rs[0] ? Object.keys(rs[0]).slice(0, 80) : [] });
    }
    const all: any[] = []; let page = 1; let url: URL | null = windowUrl(from, to, 1); let guard = 0;
    while (url && guard++ < 60) {
      const x = await apiGet(url);
      all.push(...rowsOf(x));
      const nx = nextOf(x, page);
      if (!nx) break;
      if (nx.url) url = new URL(nx.url); else { page = nx.page!; url = windowUrl(from, to, page); }
    }
    const rows = []; let skipped = 0, outside = 0; let fields: string[] = [];
    for (const it of all) {
      const n = normalise(it); fields = n.fields;
      if (!n.row) { skipped++; continue; }
      const d = callDayMelbourne(n.row.started_at as string | null);
      if (d && (d < from || d > to)) { outside++; continue; }
      rows.push(n.row);
    }
    let res = { inserted: 0, updated: 0 };
    for (let i = 0; i < rows.length; i += 200) {
      const r = await rpc("nimbata_ingest", { p_rows: rows.slice(i, i + 200), p_source: "api_reconciliation" });
      res.inserted += r.inserted || 0; res.updated += r.updated || 0;
    }
    // Completed days become final; today stays partial.
    const finalTo = to < today ? to : addDays(today, -1);
    if (from <= finalTo) await rpc("nimbata_mark_days", { p_from: from, p_to: finalTo, p_status: "final" });
    if (to >= today) await rpc("nimbata_mark_days", { p_from: today, p_to: today, p_status: "partial" });
    await logRun({ status: "ok", window_from: from, window_to: to, rows_seen: all.length, rows_inserted: res.inserted, rows_updated: res.updated,
      detail: `${mode}: ${rows.length} calls in window${skipped ? `, ${skipped} without id` : ""}${outside ? `, ${outside} outside window` : ""}` + (fields.length ? " | fields: " + safeFieldList(fields) : "") });
    return json(200, { ok: true, mode, from, to, api_rows: all.length, calls: rows.length, ...res });
  } catch (e) {
    const se = e instanceof SyncError ? e : new SyncError("api_failure", scrub(String((e as Error).message || e)));
    await logRun({ status: "error", error_category: se.category, window_from: from, window_to: to, detail: scrub(se.message).slice(0, 300) });
    return json(502, { ok: false, category: se.category, error: scrub(se.message) });
  }
});
