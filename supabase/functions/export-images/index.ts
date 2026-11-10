import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Order-list Excel export: the browser cannot download Shopify CDN photos itself (CORS), so this fetches them
// server-side and returns them as base64 for the browser to embed in the .xlsx. Shopify CDN URLs only; signed-in users only.
// If a stored photo link no longer loads (file replaced/removed), it falls back to the product's current main photo from Shopify.
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
const b64 = (u: Uint8Array) => { let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };
const CDN = /^https:\/\/cdn\.shopify\.com\//;

const SHOP = Deno.env.get("SHOPIFY_SHOP") || "bvdxj3-r8.myshopify.com";
async function productPhotos(pid: string): Promise<string[]> {
  try {
    const env = Deno.env.toObject();
    const nm = ["SHOPIFY_TOKEN", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_ADMIN_TOKEN", "SHOPIFY_ADMIN_ACCESS_TOKEN", "SHOPIFY_API_TOKEN", "SHOPIFY_ADMIN_API_TOKEN"].find((k) => env[k]) ||
      Object.keys(env).find((k) => /shopify/i.test(k) && /(token|secret|key)/i.test(k) && !/(shop$|domain|store|url)/i.test(k));
    const token = nm ? env[nm] : "";
    if (!token) return [];
    const r = await fetch(`https://${SHOP}/admin/api/2026-04/graphql.json`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": token },
      body: JSON.stringify({ query: `query($id:ID!){ product(id:$id){ media(first:6){ nodes{ preview{ image{ url } } } } } }`, variables: { id: `gid://shopify/Product/${pid}` } }),
    });
    if (!r.ok) return [];
    const o = await r.json();
    return (o?.data?.product?.media?.nodes || []).map((n: any) => n?.preview?.image?.url).filter((u: unknown) => typeof u === "string" && CDN.test(u as string));
  } catch (_) { return []; }
}
async function grab(url: string): Promise<Uint8Array | null> {
  for (const withWidth of [true, false]) {
    try {
      const u = new URL(url); if (withWidth) u.searchParams.set("width", "600");
      const r = await fetch(u.href);
      if (!r.ok) continue;
      const buf = new Uint8Array(await r.arrayBuffer());
      if (buf.length > 0 && buf.length < 4_000_000) return buf;
    } catch (_) { /* try the next way */ }
  }
  return null;
}

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
  const items: { url: string; pid: string }[] = (Array.isArray(body.items) ? body.items : (Array.isArray(body.urls) ? body.urls.map((u: unknown) => ({ url: u })) : []))
    .map((x: any) => ({ url: String(x?.url || ""), pid: /^\d{1,20}$/.test(String(x?.pid || "")) ? String(x.pid) : "" }))
    .filter((x: { url: string }) => CDN.test(x.url)).slice(0, 12);
  const images: Record<string, string> = {};
  await Promise.all(items.map(async ({ url, pid }) => {
    let buf = await grab(url);
    if (!buf && pid) { for (const alt of await productPhotos(pid)) { buf = await grab(alt); if (buf) break; } }
    if (buf) images[url] = b64(buf);
  }));
  return json({ ok: true, images });
});
