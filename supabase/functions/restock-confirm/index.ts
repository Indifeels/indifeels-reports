import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);

  const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const bearer = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const { data: who, error: whoErr } = await svc.auth.getUser(bearer);
  if (whoErr || !who?.user) return json({ error: "Not signed in" }, 401);

  const { data: prof } = await svc.from("profiles").select("is_admin,disabled").eq("id", who.user.id).single();
  if (!prof || prof.disabled) return json({ error: "Not allowed" }, 403);
  if (!prof.is_admin) {
    const { data: grant } = await svc.from("user_reports").select("report_id")
      .eq("user_id", who.user.id).eq("report_id", "restock").maybeSingle();
    if (!grant) return json({ error: "Not allowed" }, 403);
  }

  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  const items = Array.isArray(body.items) ? body.items.slice(0, 500) : [];
  const clean = items.map((i: any) => ({
    product: String(i.product || "").slice(0, 200),
    variant: String(i.variant || "").slice(0, 100),
    image: /^https:\/\/cdn\.shopify\.com\//.test(String(i.image || "")) ? String(i.image).split("?")[0] : "",
    stock: Number(i.stock) || 0,
    qty: Math.floor(Number(i.qty) || 0),
    status: String(i.status || "").slice(0, 8),
  })).filter((i: any) => i.product && i.qty > 0);
  if (!clean.length) return json({ error: "Nothing to confirm" }, 400);

  // Optional: forward to a Google Apps Script web app that appends to the supplier sheet.
  const hook = Deno.env.get("RESTOCK_SHEET_WEBHOOK");
  let sheet = false;
  if (hook) {
    try {
      const r = await fetch(hook, {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ token: Deno.env.get("RESTOCK_SHEET_TOKEN") || "", items: clean }),
        redirect: "follow",
      });
      sheet = r.ok && (await r.text()).includes("ok");
    } catch (e) { console.error("sheet webhook failed", String(e)); }
  }

  const { error } = await svc.from("restock_confirmations").insert(
    clean.map((i: any) => ({ ...i, confirmed_by: who.user.id, sheet_synced: sheet })),
  );
  if (error) { console.error(error.message); return json({ error: "Could not record the confirmation" }, 500); }
  return json({ ok: true, count: clean.length, units: clean.reduce((a: number, i: any) => a + i.qty, 0), sheet });
});
