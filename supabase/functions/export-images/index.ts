import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Order-list Excel export: the browser cannot download Shopify CDN photos itself (CORS), so this fetches them
// server-side and returns them as base64 for the browser to embed in the .xlsx. Shopify CDN URLs only; signed-in users only.
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
const b64 = (u: Uint8Array) => { let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);
  const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const { data: who, error } = await svc.auth.getUser((req.headers.get("Authorization") || "").replace(/^Bearer /, ""));
  if (error || !who?.user) return json({ error: "Not signed in" }, 401);
  const { data: prof } = await svc.from("profiles").select("disabled").eq("id", who.user.id).single();
  if (!prof || prof.disabled) return json({ error: "Not allowed" }, 403);
  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  const urls: string[] = (Array.isArray(body.urls) ? body.urls : []).map(String).filter((u: string) => /^https:\/\/cdn\.shopify\.com\//.test(u)).slice(0, 12);
  const images: Record<string, string> = {};
  await Promise.all(urls.map(async (url) => {
    try {
      const u = new URL(url); u.searchParams.set("width", "600");
      const r = await fetch(u.href);
      if (!r.ok) return;
      const buf = new Uint8Array(await r.arrayBuffer());
      if (buf.length > 4_000_000) return;
      images[url] = b64(buf);
    } catch (_) { /* that photo is skipped */ }
  }));
  return json({ ok: true, images });
});
