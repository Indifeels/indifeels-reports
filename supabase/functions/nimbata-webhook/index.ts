// nimbata-webhook — receives Nimbata "After Every Call" webhooks and UPSERTs them into public.nimbata_calls.
// Auth: shared secret token, accepted as ?key=<token>, "Authorization: Bearer <token>", "x-webhook-token",
// or as the password of Basic auth. Only its SHA-256 is stored (integration_config.nimbata_webhook_token_sha256).
// verify_jwt is OFF because Nimbata cannot send a Supabase JWT; the token check above replaces it.
import { normalise, safeFieldList } from "./nimbata_normalize.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const H = { apikey: SERVICE_KEY, Authorization: "Bearer " + SERVICE_KEY, "Content-Type": "application/json" };

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

async function sha256(s: string): Promise<string> {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function timingSafeEq(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function logRun(status: string, category: string | null, detail: string, rows = 0, ins = 0, upd = 0) {
  try {
    await fetch(SUPABASE_URL + "/rest/v1/integration_sync_runs", {
      method: "POST", headers: { ...H, Prefer: "return=minimal" },
      body: JSON.stringify({ integration: "nimbata", run_type: "webhook", status, error_category: category,
        detail: detail.slice(0, 500), rows_seen: rows, rows_inserted: ins, rows_updated: upd, finished_at: new Date().toISOString() }),
    });
  } catch (_) { /* logging must never break ingestion */ }
}

function presentedToken(req: Request): string {
  const u = new URL(req.url);
  const q = u.searchParams.get("key") || u.searchParams.get("token");
  if (q) return q;
  const a = req.headers.get("authorization") || "";
  if (/^bearer\s+/i.test(a)) return a.replace(/^bearer\s+/i, "").trim();
  if (/^basic\s+/i.test(a)) {
    try { const dec = atob(a.replace(/^basic\s+/i, "").trim()); return dec.slice(dec.indexOf(":") + 1); } catch (_) { return ""; }
  }
  return req.headers.get("x-webhook-token") || req.headers.get("x-api-key") || "";
}

async function parseBody(req: Request): Promise<unknown> {
  const ct = (req.headers.get("content-type") || "").toLowerCase();
  const text = await req.text();
  if (!text.trim()) throw new Error("empty body");
  if (ct.includes("application/x-www-form-urlencoded")) return Object.fromEntries(new URLSearchParams(text));
  return JSON.parse(text);
}

Deno.serve(async (req: Request) => {
  if (req.method === "GET") return json(200, { ok: true, service: "nimbata-webhook" }); // reachability check only, no data
  if (req.method !== "POST") return json(405, { ok: false, error: "method not allowed" });

  // ---- authenticate
  let expected = "";
  try {
    const r = await fetch(SUPABASE_URL + "/rest/v1/integration_config?key=eq.nimbata_webhook_token_sha256&select=value", { headers: H });
    expected = (await r.json())?.[0]?.value || "";
  } catch (_) { /* handled below */ }
  if (!expected) { await logRun("error", "db_failure", "webhook token not configured or config unreadable"); return json(503, { ok: false, error: "not configured" }); }
  const tok = presentedToken(req);
  if (!tok || !timingSafeEq(await sha256(tok), expected)) {
    await logRun("rejected", "webhook_auth", "invalid or missing webhook token");
    return json(401, { ok: false, error: "unauthorized" });
  }

  // ---- parse
  let body: unknown;
  try { body = await parseBody(req); }
  catch (e) { await logRun("error", "malformed_payload", "could not parse body: " + (e as Error).message.slice(0, 120)); return json(400, { ok: false, error: "malformed payload" }); }

  const items: Record<string, unknown>[] = Array.isArray(body) ? body as any
    : Array.isArray((body as any)?.calls) ? (body as any).calls
    : Array.isArray((body as any)?.data) ? (body as any).data
    : [body as Record<string, unknown>];

  const rows = []; const problems: string[] = []; let fields: string[] = [];
  for (const it of items) {
    if (!it || typeof it !== "object") { problems.push("non-object item"); continue; }
    const n = normalise(it);
    fields = n.fields;
    if (n.row) rows.push(n.row); else problems.push(n.error || "unparseable");
  }
  if (!rows.length) {
    await logRun("error", "malformed_payload", problems.join("; ") + " | fields: " + safeFieldList(fields), items.length);
    return json(422, { ok: false, error: "no usable call in payload", detail: problems });
  }

  // ---- upsert (idempotent on nimbata_call_id)
  const r = await fetch(SUPABASE_URL + "/rest/v1/rpc/nimbata_ingest", {
    method: "POST", headers: H, body: JSON.stringify({ p_rows: rows, p_source: "webhook" }),
  });
  if (!r.ok) {
    const t = (await r.text()).slice(0, 200);
    await logRun("error", "db_failure", "nimbata_ingest failed HTTP " + r.status + ": " + t, rows.length);
    return json(500, { ok: false, error: "storage failed" }); // non-2xx lets Nimbata know delivery failed
  }
  const res = await r.json();
  const test = rows.every((x) => x.is_test);
  await logRun("ok", null, (test ? "TEST payload (quarantined) | " : "") + "fields: " + safeFieldList(fields),
    rows.length, res.inserted || 0, res.updated || 0);
  return json(200, { ok: true, calls: rows.length, inserted: res.inserted, updated: res.updated, test_payload: test || undefined });
});
