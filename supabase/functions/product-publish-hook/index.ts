// Shopify products/create + products/update webhook -> rebuild the Stock Take and Transfer report data
// so a product that was just added or published shows up on the Barcodes page within minutes.
// Auth: shared secret in ?k= (stored in table product_hook_key, readable by the service role only). Only reacts to ACTIVE products created or published in the last 30 minutes.
import { createClient } from "npm:@supabase/supabase-js@2";
const repo = "Indifeels/indifeels-reports";
const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
const ok = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return ok({ error: "Use POST" }, 405);
  const { data: kr } = await svc.from("product_hook_key").select("k").limit(1).maybeSingle();
  const key = kr?.k || "";
  if (!key || new URL(req.url).searchParams.get("k") !== key) return ok({ error: "Not authorized" }, 401);
  let p: any = {};
  try { p = await req.json(); } catch { return ok({ ok: true, skipped: "no body" }); }
  const t = (x: unknown) => { const n = Date.parse(String(x || "")); return Number.isFinite(n) ? n : 0; };
  const fresh = Math.max(t(p.created_at), t(p.published_at));
  if (String(p.status || "").toLowerCase() !== "active" || !fresh || Date.now() - fresh > 30 * 60000) return ok({ ok: true, skipped: "not a newly added or published product" });
  const token = Deno.env.get("GITHUB_DISPATCH_TOKEN");
  if (!token) return ok({ error: "GitHub dispatch credential is missing" }, 500);
  const r = await fetch("https://api.github.com/repos/" + repo + "/dispatches", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "IndiFeels-Product-Hook" },
    body: JSON.stringify({ event_type: "product-published", client_payload: { product_id: String(p.id || ""), title: String(p.title || "").slice(0, 120) } }),
  });
  if (!r.ok) return ok({ error: "GitHub returned HTTP " + r.status }, 502);
  return ok({ ok: true, dispatched: true });
});
