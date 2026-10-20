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
  const env = Deno.env.toObject();
  const nm = ["SHOPIFY_TOKEN", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_ADMIN_TOKEN", "SHOPIFY_ADMIN_ACCESS_TOKEN", "SHOPIFY_API_TOKEN", "SHOPIFY_ADMIN_API_TOKEN"].find((k) => env[k]) ||
    Object.keys(env).find((k) => /shopify/i.test(k) && /(token|secret|key)/i.test(k) && !/(shop$|domain|store|url)/i.test(k));
  const token = nm ? env[nm] : "";
  if (!token) throw new Error("SHOPIFY_TOKEN is not set on the Supabase function. Shopify-like names here: " + (Object.keys(env).filter((k) => /shop/i.test(k)).join(", ") || "none"));
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

/* ---------------- bulk transfer between Shopify locations ---------------- */
const LOCID = /^gid:\/\/shopify\/Location\/\d{1,20}$/;
const toLoc = (x: unknown) => { const s = String(x || ""); return /^\d{1,20}$/.test(s) ? `gid://shopify/Location/${s}` : s; };
const chunk = <T,>(a: T[], n: number) => { const o: T[][] = []; for (let i = 0; i < a.length; i += n) o.push(a.slice(i, i + n)); return o; };

async function bulk(body: any) {
  if (body.action === "locations") {
    let list: { id: string; name: string }[] = [];
    try {
      const d = await gql(`query{ locations(first:50){ nodes{ id name isActive } } }`, {});
      list = d.locations.nodes.filter((l: any) => l.isActive).map((l: any) => ({ id: l.id, name: l.name }));
    } catch (_) { /* token may lack read_locations: fall back to the two known ones */ }
    if (!list.length) list = [{ id: SHOPLOC, name: "Shop location" }, { id: BACKUP, name: "Backup" }];
    return json({ ok: true, locations: list.map((l) => ({ id: l.id.split("/").pop(), name: l.name })) });
  }

  if (body.action === "setcounts") {
    // Stock take -> website: set available stock at ONE location to the counted numbers
    const loc = toLoc(body.loc);
    if (!LOCID.test(loc)) return json({ error: "Pick the location" }, 400);
    const add = body.mode === "add"; // stock take on an empty location: scanned numbers are ADDED to current stock
    const want = new Map<string, number>();
    for (const it of Array.isArray(body.items) ? body.items.slice(0, 2500) : []) {
      const v = String(it?.vid || ""), n = Math.trunc(Number(it?.qty));
      if (!/^\d{1,20}$/.test(v) || !Number.isFinite(n) || n < 0 || n > 100000) return json({ error: "Bad item in the list" }, 400);
      if (add && n < 1) continue;
      want.set(v, n);
    }
    if (!want.size) return json({ error: "Nothing to push" }, 400);
    const READ1 = `query($ids:[ID!]!,$l:ID!){ nodes(ids:$ids){ ... on ProductVariant{ id title product{ title } inventoryItem{ id
      f: inventoryLevel(locationId:$l){ quantities(names:["available"]){ quantity } } } } } }`;
    const rows: { vid: string; item: string; title: string; cur: number; has: boolean; qty: number }[] = [];
    for (const ids of chunk([...want.keys()], 50)) {
      const d = await gql(READ1, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`), l: loc });
      d.nodes.forEach((n: any) => {
        if (!n) return; // variant deleted since the count: skip it
        const vid = n.id.split("/").pop();
        rows.push({ vid, item: n.inventoryItem.id, title: `${n.product?.title || ""} ${n.title || ""}`.trim(), cur: q(n.inventoryItem.f), has: !!n.inventoryItem.f, qty: add ? q(n.inventoryItem.f) + want.get(vid)! : want.get(vid)! });
      });
    }
    const chg = rows.filter((r) => r.qty !== r.cur);
    const up = chg.filter((r) => r.qty > r.cur), down = chg.filter((r) => r.qty < r.cur);
    const summary = {
      variants: rows.length, changed: chg.length, same: rows.length - chg.length,
      up: up.length, down: down.length,
      unitsUp: up.reduce((a, r) => a + r.qty - r.cur, 0), unitsDown: down.reduce((a, r) => a + r.cur - r.qty, 0),
      toZero: down.filter((r) => r.qty === 0).length,
    };
    if (body.dry) return json({ ok: true, dry: true, ...summary });
    for (const r of chg) if (!r.has) {
      const a = await gql(`mutation($i:ID!,$l:ID!){ inventoryActivate(inventoryItemId:$i, locationId:$l){ userErrors{ message } } }`, { i: r.item, l: loc });
      const e = a.inventoryActivate.userErrors; if (e?.length) throw new Error(`${r.title}: ${e[0].message}`);
    }
    const ref = "indifeels://stock-take/" + crypto.randomUUID();
    let done = 0;
    for (const part of chunk(chg, 100)) {
      const m = await gql(`mutation($input: InventoryAdjustQuantitiesInput!, $key: String!){ inventoryAdjustQuantities(input:$input) @idempotent(key:$key){ inventoryAdjustmentGroup{ id } userErrors{ message } } }`,
        { key: crypto.randomUUID(), input: { name: "available", reason: "correction", referenceDocumentUri: ref,
          changes: part.map((r) => ({ inventoryItemId: r.item, locationId: loc, delta: r.qty - r.cur, changeFromQuantity: r.has ? r.cur : 0 })) } });
      const ue = m.inventoryAdjustQuantities.userErrors;
      if (ue?.length) return json({ error: `Updated ${done} of ${chg.length} variants, then Shopify stopped: ${ue[0].message}. Push again to finish the rest.`, updated: done }, 500);
      done += part.length;
    }
    const k = loc === SHOPLOC ? "melbourne_stock" : loc === BACKUP ? "storage_stock" : "";
    let warn = "";
    if (k) {
      const mfs = chg.map((r) => ({ ownerId: `gid://shopify/ProductVariant/${r.vid}`, namespace: "custom", key: k, type: "number_integer", value: String(r.qty) }));
      for (const part of chunk(mfs, 25)) {
        const mf = await gql(`mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{ message } } }`, { m: part });
        const me = mf.metafieldsSet.userErrors;
        if (me?.length) { warn = "Stock updated, but the website ST number didn't update for some items: " + me[0].message; break; }
      }
    }
    return json({ ok: true, ...summary, ...(warn ? { warn } : {}) });
  }

  const from = toLoc(body.from), to = toLoc(body.to);
  if (!LOCID.test(from) || !LOCID.test(to)) return json({ error: "Pick both locations" }, 400);
  if (from === to) return json({ error: "From and To must be different locations" }, 400);

  if (body.action === "lookup") {
    const raw = String(body.code || "").trim();
    if (!/^[0-9A-Za-z._-]{3,40}$/.test(raw)) return json({ error: "Bad barcode" }, 400);
    const Q = `query($q:String!,$from:ID!,$to:ID!){ productVariants(first:3, query:$q){ nodes{ id title barcode image{ url } product{ title featuredMedia{ preview{ image{ url } } } }
      inventoryItem{ id f: inventoryLevel(locationId:$from){ quantities(names:["available"]){ quantity } } t: inventoryLevel(locationId:$to){ quantities(names:["available"]){ quantity } } } } } }`;
    const tries = [raw]; if (/^0+\d/.test(raw)) tries.push(raw.replace(/^0+/, ""));
    for (const c of tries) {
      const d = await gql(Q, { q: `barcode:${c}`, from, to });
      const norm = (s: string) => String(s || "").replace(/\D/g, "").replace(/^0+/, "");
      const n = d.productVariants.nodes.find((v: any) => norm(v.barcode) === norm(c) || v.barcode === c) || d.productVariants.nodes[0];
      if (n) {
        const img = n.image?.url || n.product?.featuredMedia?.preview?.image?.url || "";
        return json({ ok: true, found: true, vid: n.id.split("/").pop(), product: n.product?.title || "", variant: n.title || "", image: img,
          from: q(n.inventoryItem.f), to: q(n.inventoryItem.t), fromStocked: !!n.inventoryItem.f });
      }
    }
    return json({ ok: true, found: false });
  }

  // transfer
  const merged = new Map<string, number>();
  for (const it of Array.isArray(body.items) ? body.items.slice(0, 500) : []) {
    const v = String(it?.vid || ""), n = Math.trunc(Number(it?.qty) || 0);
    if (!/^\d{1,20}$/.test(v) || n < 1 || n > 1000) return json({ error: "Bad item in the list" }, 400);
    merged.set(v, (merged.get(v) || 0) + n);
  }
  if (!merged.size) return json({ error: "Nothing to transfer" }, 400);

  const READ = `query($ids:[ID!]!,$from:ID!,$to:ID!){ nodes(ids:$ids){ ... on ProductVariant{ id title product{ title } inventoryItem{ id
    f: inventoryLevel(locationId:$from){ quantities(names:["available"]){ quantity } } t: inventoryLevel(locationId:$to){ quantities(names:["available"]){ quantity } } } } } }`;
  const rows: { vid: string; item: string; title: string; fq: number; tq: number; hasTo: boolean; qty: number }[] = [];
  for (const ids of chunk([...merged.keys()], 50)) {
    const d = await gql(READ, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`), from, to });
    d.nodes.forEach((n: any, i: number) => {
      if (!n) throw new Error("A variant in the list no longer exists");
      const vid = n.id.split("/").pop();
      rows.push({ vid, item: n.inventoryItem.id, title: `${n.product?.title || ""} ${n.title || ""}`.trim(), fq: q(n.inventoryItem.f), tq: q(n.inventoryItem.t), hasTo: !!n.inventoryItem.t, qty: merged.get(vid)! });
    });
  }
  // check everything BEFORE moving anything
  const short = rows.filter((r) => r.qty > r.fq);
  if (short.length) return json({ error: "Not enough stock at the From location for: " + short.slice(0, 5).map((r) => `${r.title} (has ${r.fq}, scanned ${r.qty})`).join("; ") + (short.length > 5 ? ` and ${short.length - 5} more` : ""), short: short.map((r) => r.vid) }, 400);

  for (const r of rows) if (!r.hasTo) {
    const a = await gql(`mutation($i:ID!,$l:ID!){ inventoryActivate(inventoryItemId:$i, locationId:$l){ userErrors{ message } } }`, { i: r.item, l: to });
    const e = a.inventoryActivate.userErrors; if (e?.length) throw new Error(`${r.title}: ${e[0].message}`);
  }
  const key = crypto.randomUUID();
  let done = 0;
  for (const part of chunk(rows, 100)) {
    const changes: unknown[] = [];
    part.forEach((r) => { changes.push({ inventoryItemId: r.item, locationId: from, delta: -r.qty, changeFromQuantity: r.fq }); changes.push({ inventoryItemId: r.item, locationId: to, delta: r.qty, changeFromQuantity: r.hasTo ? r.tq : 0 }); });
    const m = await gql(`mutation($input: InventoryAdjustQuantitiesInput!, $key: String!){ inventoryAdjustQuantities(input:$input) @idempotent(key:$key){ inventoryAdjustmentGroup{ id } userErrors{ message } } }`,
      { key: crypto.randomUUID(), input: { name: "available", reason: "correction", referenceDocumentUri: "indifeels://restock/bulk-transfer/" + key, changes } });
    const ue = m.inventoryAdjustQuantities.userErrors;
    if (ue?.length) return json({ error: `Moved ${done} of ${rows.length} variants, then Shopify stopped: ${ue[0].message}. Check the list and finalize the rest again.`, moved: done }, 500);
    done += part.length;
  }

  // website ST numbers: custom.melbourne_stock = Shop location, custom.storage_stock = Backup
  const mfs: unknown[] = [];
  rows.forEach((r) => {
    const set = (loc: string, val: number) => {
      const k = loc === SHOPLOC ? "melbourne_stock" : loc === BACKUP ? "storage_stock" : "";
      if (k) mfs.push({ ownerId: `gid://shopify/ProductVariant/${r.vid}`, namespace: "custom", key: k, type: "number_integer", value: String(Math.max(0, val)) });
    };
    set(from, r.fq - r.qty); set(to, (r.hasTo ? r.tq : 0) + r.qty);
  });
  let warn = "";
  for (const part of chunk(mfs, 25)) {
    const mf = await gql(`mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{ message } } }`, { m: part });
    const me = mf.metafieldsSet.userErrors;
    if (me?.length) { warn = "Stock moved, but the website ST number didn't update for some items: " + me[0].message; break; }
  }
  return json({ ok: true, variants: rows.length, units: rows.reduce((a, r) => a + r.qty, 0), ...(warn ? { warn } : {}) });
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
  if (body.action === "locations" || body.action === "lookup" || body.action === "transfer" || body.action === "setcounts") {
    try { return await bulk(body); } catch (e) { return json({ error: String((e as Error)?.message || e).slice(0, 300) }, 500); }
  }
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
