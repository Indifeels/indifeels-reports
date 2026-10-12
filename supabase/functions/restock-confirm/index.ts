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

  // "asof" is the report's data cut-off the user was looking at. Remembering it per variant means the next
  // Restock build only counts sales made after it: nothing is fetched twice, and the item returns only if it sells again.
  const t = Date.parse(String(body.asof || ""));
  const asof = Number.isFinite(t) ? new Date(Math.min(t, Date.now())).toISOString() : null;
  const mark = async (rows: any[], reason: string) => {
    const list = rows
      .map((r: any) => ({ vid: String(r?.vid || ""), asof }))
      .filter((r: any) => /^\d{1,20}$/.test(r.vid) && r.asof);
    if (!list.length) return 0;
    const { error: e } = await svc.rpc("restock_mark_cleared", { p_rows: list, p_user: who.user.id, p_reason: reason });
    if (e) { console.error(e.message); throw new Error("mark"); }
    return list.length;
  };

  if (body.action === "clear") {
    if (!asof) return json({ error: "Missing report time" }, 400);
    try {
      const n = await mark(Array.isArray(body.items) ? body.items.slice(0, 500) : [], "deleted");
      return json({ ok: true, cleared: n });
    } catch { return json({ error: "Could not save the removal" }, 500); }
  }

  const items = Array.isArray(body.items) ? body.items.slice(0, 500) : [];
  const clean = items.map((i: any) => ({
    product: String(i.product || "").slice(0, 200),
    variant: String(i.variant || "").slice(0, 100),
    vid: String(i.vid || "").slice(0, 20),
    image: /^https:\/\/cdn\.shopify\.com\//.test(String(i.image || "")) ? String(i.image).split("?")[0] : "",
    url: /^https:\/\/(www\.)?indifeels\.com\/products\//.test(String(i.url || "")) ? String(i.url).split("?")[0].slice(0, 300) : "",
    stock: Number(i.stock) || 0,
    qty: Math.floor(Number(i.qty) || 0),
    status: String(i.status || "").slice(0, 8),
  })).filter((i: any) => i.product && i.qty > 0);
  if (!clean.length) return json({ error: "Nothing to confirm" }, 400);

  // Remember these variants as handled before anything is sent, so a failure here changes nothing.
  try { await mark(clean, "confirmed"); } catch { return json({ error: "Could not record the confirmation. Nothing was changed." }, 500); }

  // Append to the supplier sheet through the Google Apps Script web app. Any earlier confirmations that never reached
  // the sheet are sent in the same call, so the sheet catches up the moment the connection works again.
  const melb = (iso: string) => {
    const p: Record<string, string> = {};
    new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Melbourne", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(iso)).forEach((x) => { p[x.type] = x.value; });
    return `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute}`;
  };
  const { data: backlog } = await svc.from("restock_confirmations")
    .select("id,product,variant,image,url,stock,qty,status,confirmed_at")
    .eq("sheet_synced", false).gte("confirmed_at", new Date(Date.now() - 30 * 864e5).toISOString())
    .order("id", { ascending: true }).limit(200);
  const nowAt = melb(new Date().toISOString());
  const hook = Deno.env.get("RESTOCK_SHEET_WEBHOOK");
  let sheet = false;
  let sheetErr = "";
  if (!hook) {
    sheetErr = "RESTOCK_SHEET_WEBHOOK is not set in Supabase secrets";
  } else {
    try {
      const outgoing = [
        ...(backlog || []).map((r: any) => ({ product: r.product, variant: r.variant, image: r.image, url: r.url, stock: r.stock, qty: r.qty, status: r.status, at: melb(r.confirmed_at) })),
        ...clean.map(({ vid: _v, ...r }: any) => ({ ...r, at: nowAt })),
      ];
      const r = await fetch(hook, {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ token: Deno.env.get("RESTOCK_SHEET_TOKEN") || "", items: outgoing }),
        redirect: "follow",
        signal: AbortSignal.timeout(20000),
      });
      const txt = await r.text();
      sheet = r.ok && txt.trim().toLowerCase() === "ok";
      if (!sheet) {
        const plain = txt.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 160);
        sheetErr = `Sheet script replied HTTP ${r.status}: ${plain || "(empty)"}`;
      }
    } catch (e) { sheetErr = "Sheet script unreachable: " + String(e).slice(0, 160); }
    if (sheetErr) console.error("sheet webhook failed:", sheetErr);
  }
  if (sheet && backlog?.length) {
    await svc.from("restock_confirmations").update({ sheet_synced: true, sheet_error: null }).in("id", backlog.map((r: any) => r.id));
  }

  const { error } = await svc.from("restock_confirmations").insert(
    clean.map(({ vid: _v, ...i }: any) => ({ ...i, confirmed_by: who.user.id, sheet_synced: sheet, sheet_error: sheet ? null : sheetErr })),
  );
  if (error) { console.error(error.message); return json({ error: "Could not record the confirmation" }, 500); }
  return json({ ok: true, count: clean.length, units: clean.reduce((a: number, i: any) => a + i.qty, 0), sheet, sheet_error: sheet ? "" : sheetErr, caught_up: sheet ? (backlog?.length || 0) : 0 });
});
