import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Daily report: link an ad set to a product page so its variant stock shows as a bar.
//   { action: "set",   adset_id, url }  -> saves the link, returns { ok, title, handle, n, a, asof, live }
//   { action: "clear", adset_id }       -> removes the link
// n = variants, a = variants with stock. Live Shopify is used when SHOPIFY_TOKEN is set on this function,
// otherwise the synced voice_product_cache (as of its last sync, returned in "asof").

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });

const SHOP = Deno.env.get("SHOPIFY_SHOP") || "bvdxj3-r8.myshopify.com";

function handleFromUrl(raw: string): string | null {
  let u: URL;
  try { u = new URL(String(raw || "").trim()); } catch { return null; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  const host = u.hostname.toLowerCase();
  if (!(host === "indifeels.com" || host.endsWith(".indifeels.com") || host.endsWith(".myshopify.com"))) return null;
  const m = u.pathname.match(/\/products\/([^/?#]+)/i);
  if (!m) return null;
  let h = m[1];
  try { h = decodeURIComponent(h); } catch { /* keep raw */ }
  h = h.toLowerCase();
  return /^[a-z0-9][a-z0-9._-]{0,254}$/.test(h) ? h : null;
}

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
      .eq("user_id", who.user.id).eq("report_id", "daily").maybeSingle();
    if (!grant) return json({ error: "Not allowed" }, 403);
  }

  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  const adsetId = String(body.adset_id || "");
  if (!/^\d{5,25}$/.test(adsetId)) return json({ error: "Bad ad set" }, 400);

  if (body.action === "clear") {
    const { error } = await svc.from("adset_product_links").delete().eq("adset_id", adsetId);
    if (error) { console.error(error.message); return json({ error: "Could not remove the link" }, 500); }
    return json({ ok: true });
  }
  if (body.action !== "set") return json({ error: "Bad request" }, 400);

  const handle = handleFromUrl(body.url);
  if (!handle) return json({ error: "That doesn't look like an Indifeels product link (it should contain /products/...)" }, 400);

  // Look the product up so the link is checked before it is saved.
  let title = "", n = 0, a = 0, asof = "", live = false;
  const token = Deno.env.get("SHOPIFY_TOKEN");
  if (token) {
    try {
      const r = await fetch(`https://${SHOP}/admin/api/2026-04/graphql.json`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": token },
        body: JSON.stringify({
          query: `query($q:String!){ products(first:1,query:$q){ nodes{ title handle variants(first:100){nodes{inventoryQuantity}} } } }`,
          variables: { q: `handle:${handle}` },
        }),
      });
      const x = await r.json();
      const p = x?.data?.products?.nodes?.[0];
      if (p && String(p.handle).toLowerCase() === handle) {
        title = p.title; const v = p.variants.nodes;
        n = v.length; a = v.filter((i: any) => (i.inventoryQuantity || 0) > 0).length; asof = new Date().toISOString(); live = true;
      }
    } catch (e) { console.error("shopify lookup failed", String(e)); }
  }
  if (!live) {
    const { data: p } = await svc.from("voice_product_cache").select("title,variants,synced_at").eq("handle", handle).maybeSingle();
    if (p && Array.isArray(p.variants) && p.variants.length) {
      title = p.title; n = p.variants.length;
      a = p.variants.filter((i: any) => (Number(i.inventory_quantity) || 0) > 0).length; asof = p.synced_at;
    }
  }
  if (!n) return json({ error: "Couldn't find that product on the store. Check the link." }, 404);

  const { error } = await svc.from("adset_product_links").upsert(
    { adset_id: adsetId, handle, title, linked_by: who.user.id, updated_at: new Date().toISOString() },
    { onConflict: "adset_id" },
  );
  if (error) { console.error(error.message); return json({ error: "Could not save the link" }, 500); }
  return json({ ok: true, title, handle, n, a, asof, live });
});
