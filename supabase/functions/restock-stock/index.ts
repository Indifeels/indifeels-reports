import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Restock Planner: long-press a variant's Stock tile -> read / adjust stock at both Shopify locations.
// Admin only. Writes Shopify inventory (Shop location + Backup) and the front-end ST metafields
// (custom.melbourne_stock = Shop location, custom.storage_stock = Backup), because Shopify Flow does not fire for API changes.
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });

const SHOP = Deno.env.get("SHOPIFY_SHOP") || "bvdxj3-r8.myshopify.com";
const API = `https://${SHOP}/admin/api/2026-04/graphql.json`;
const BACKUP = "gid://shopify/Location/99841048933", SHOPLOC = "gid://shopify/Location/99623436645";

async function gql(query: string, variables: Record<string, unknown>) {
  const token = Deno.env.get("SHOPIFY_TOKEN");
  if (!token) throw new Error("SHOPIFY_TOKEN is not set on the Supabase function");
  for (let a = 0; a < 3; a++) {
    const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": token }, body: JSON.stringify({ query, variables }) });
    if ((r.status === 429 || r.status >= 500) && a < 2) { await new Promise((x) => setTimeout(x, 1500 * (a + 1))); continue; }
    if (!r.ok) throw new Error(`Shopify returned HTTP ${r.status}`);
    const o = await r.json();
    if (o.errors) {
      if (JSON.stringify(o.errors).includes("THROTTLED") && a < 2) { await new Promise((x) => setTimeout(x, 2000)); continue; }
      throw new Error("Shopify: " + JSON.stringify(o.errors).slice(0, 160));
    }
    return o.data;
  }
  throw new Error("Shopify kept throttling");
}

const LEVELS = `query($id:ID!){ productVariant(id:$id){ id title product{ title } inventoryItem{ id
  s: inventoryLevel(locationId:"${SHOPLOC}"){ quantities(names:["available"]){quantity} }
  b: inventoryLevel(locationId:"${BACKUP}"){ quantities(names:["available"]){quantity} } } } }`;
const q = (x: any) => (x?.quantities?.[0]?.quantity ?? 0) as number;

async function read(vid: string) {
  const d = await gql(LEVELS, { id: `gid://shopify/ProductVariant/${vid}` });
  const v = d.productVariant;
  if (!v) throw new Error("Variant not found");
  return { v, item: v.inventoryItem.id as string, shop: q(v.inventoryItem.s), backup: q(v.inventoryItem.b), hasShop: !!v.inventoryItem.s, hasBackup: !!v.inventoryItem.b };
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);

  const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const bearer = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const { data: who, error: whoErr } = await svc.auth.getUser(bearer);
  if (whoErr || !who?.user) return json({ error: "Not signed in" }, 401);
  const { data: prof } = await svc.from("profiles").select("is_admin,disabled").eq("id", who.user.id).single();
  if (!prof || prof.disabled || !prof.is_admin) return json({ error: "Only the owner can change stock" }, 403);

  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  const vid = String(body.vid || "");
  if (!/^\d{1,20}$/.test(vid)) return json({ error: "Bad variant" }, 400);

  try {
    if (body.action === "get") {
      const r = await read(vid);
      return json({ ok: true, shop: r.shop, backup: r.backup, title: r.v.title, product: r.v.product?.title || "" });
    }
    if (body.action === "adjust") {
      const dS = Math.trunc(Number(body.dShop) || 0), dB = Math.trunc(Number(body.dBackup) || 0);
      if (Math.abs(dS) > 1000 || Math.abs(dB) > 1000) return json({ error: "Adjustment too large" }, 400);
      if (!dS && !dB) return json({ error: "Nothing to change" }, 400);
      const r = await read(vid);
      const nS = r.shop + dS, nB = r.backup + dB;
      if (dS && nS < 0) return json({ error: `Shop location can't go below 0 (now ${r.shop})` }, 400);
      if (dB && nB < 0) return json({ error: `Backup can't go below 0 (now ${r.backup})` }, 400);
      // a location the variant isn't stocked at yet has to be activated before it can hold stock
      for (const [d, has, loc] of [[dS, r.hasShop, SHOPLOC], [dB, r.hasBackup, BACKUP]] as [number, boolean, string][]) {
        if (d > 0 && !has) {
          const a = await gql(`mutation($i:ID!,$l:ID!){ inventoryActivate(inventoryItemId:$i, locationId:$l){ userErrors{ message } } }`, { i: r.item, l: loc });
          const e = a.inventoryActivate.userErrors; if (e?.length) throw new Error(e[0].message);
        }
      }
      const changes: unknown[] = [];
      if (dS) changes.push({ inventoryItemId: r.item, locationId: SHOPLOC, delta: dS, changeFromQuantity: r.shop });
      if (dB) changes.push({ inventoryItemId: r.item, locationId: BACKUP, delta: dB, changeFromQuantity: r.backup });
      const m = await gql(`mutation($input: InventoryAdjustQuantitiesInput!, $key: String!){ inventoryAdjustQuantities(input:$input) @idempotent(key:$key){ inventoryAdjustmentGroup{ id } userErrors{ message } } }`,
        { key: crypto.randomUUID(), input: { name: "available", reason: "correction", referenceDocumentUri: "indifeels://restock/stock-edit", changes } });
      const ue = m.inventoryAdjustQuantities.userErrors; if (ue?.length) throw new Error(ue[0].message);
      const mf = await gql(`mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{ message } } }`, { m: [
        { ownerId: `gid://shopify/ProductVariant/${vid}`, namespace: "custom", key: "melbourne_stock", type: "number_integer", value: String(nS) },
        { ownerId: `gid://shopify/ProductVariant/${vid}`, namespace: "custom", key: "storage_stock", type: "number_integer", value: String(nB) } ] });
      const me = mf.metafieldsSet.userErrors;
      if (me?.length) return json({ ok: true, shop: nS, backup: nB, warn: "Stock saved, but the website ST number didn't update: " + me[0].message });
      return json({ ok: true, shop: nS, backup: nB });
    }
    return json({ error: "Unknown action" }, 400);
  } catch (e) {
    return json({ error: String((e as Error)?.message || e).slice(0, 200) }, 500);
  }
});
