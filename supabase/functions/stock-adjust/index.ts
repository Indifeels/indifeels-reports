import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Stock Take and Transfer -> "Add / remove" tab. Admin only.
//  adjustlist : add or remove pieces at ONE Shopify location for a list of variants (+ website ST metafield)
//  setbarcode : put a barcode on a variant that has none
//  createvariant : create a missing size (variant) on a product, with a barcode
//  labelqueue : barcode labels to print on the next run of the Indifeels label template (table label_queue)
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });

const SHOP = Deno.env.get("SHOPIFY_SHOP") || "bvdxj3-r8.myshopify.com";
const API = `https://${SHOP}/admin/api/2026-04/graphql.json`;
const BACKUP = "gid://shopify/Location/99841048933", SHOPLOC = "gid://shopify/Location/99623436645";

async function gql(query: string, variables: Record<string, unknown>) {
  const env = Deno.env.toObject();
  const nm = ["SHOPIFY_TOKEN", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_ADMIN_TOKEN", "SHOPIFY_ADMIN_ACCESS_TOKEN", "SHOPIFY_API_TOKEN", "SHOPIFY_ADMIN_API_TOKEN"].find((k) => env[k]) ||
    Object.keys(env).find((k) => /shopify/i.test(k) && /(token|secret|key)/i.test(k) && !/(shop$|domain|store|url)/i.test(k));
  const token = nm ? env[nm] : "";
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

const q = (x: any) => (x?.quantities?.[0]?.quantity ?? 0) as number;
const LOCID = /^gid:\/\/shopify\/Location\/\d{1,20}$/;
const toLoc = (x: unknown) => { const s = String(x || ""); return /^\d{1,20}$/.test(s) ? `gid://shopify/Location/${s}` : s; };
const chunk = <T,>(a: T[], n: number) => { const o: T[][] = []; for (let i = 0; i < a.length; i += n) o.push(a.slice(i, i + n)); return o; };
const VID = /^\d{1,20}$/;

function items(body: any, max: number, cap: number) {
  const m = new Map<string, number>();
  for (const it of Array.isArray(body.items) ? body.items.slice(0, max) : []) {
    const v = String(it?.vid || ""), n = Math.trunc(Number(it?.qty ?? it?.copies));
    if (!VID.test(v) || !Number.isFinite(n) || n < 1 || n > cap) throw new Error("Bad item in the list");
    m.set(v, (m.get(v) || 0) + n);
  }
  return m;
}

async function adjustList(body: any, svc: any, by: string) {
  const loc = toLoc(body.loc);
  if (!LOCID.test(loc)) return json({ error: "Pick the location" }, 400);
  const mode = body.mode === "remove" ? "remove" : "add", sign = mode === "add" ? 1 : -1;
  const want = items(body, 500, 1000);
  if (!want.size) return json({ error: "Nothing in the list" }, 400);
  const READ = `query($ids:[ID!]!,$l:ID!){ nodes(ids:$ids){ ... on ProductVariant{ id title product{ title } inventoryItem{ id
    f: inventoryLevel(locationId:$l){ quantities(names:["available"]){ quantity } } } } } }`;
  const rows: { vid: string; item: string; title: string; cur: number; has: boolean; qty: number }[] = [];
  for (const ids of chunk([...want.keys()], 50)) {
    const d = await gql(READ, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`), l: loc });
    d.nodes.forEach((n: any) => {
      if (!n) throw new Error("A variant in the list no longer exists");
      const vid = n.id.split("/").pop();
      rows.push({ vid, item: n.inventoryItem.id, title: `${n.product?.title || ""} ${n.title || ""}`.trim(), cur: q(n.inventoryItem.f), has: !!n.inventoryItem.f, qty: want.get(vid)! });
    });
  }
  if (mode === "remove") {
    const short = rows.filter((r) => r.qty > r.cur);
    if (short.length) return json({ error: "Not enough stock there to remove: " + short.slice(0, 5).map((r) => `${r.title} (has ${r.cur}, removing ${r.qty})`).join("; ") + (short.length > 5 ? ` and ${short.length - 5} more` : ""), short: short.map((r) => r.vid) }, 400);
  }
  if (body.dry) return json({ ok: true, dry: true, variants: rows.length, units: rows.reduce((a, r) => a + r.qty, 0) });
  if (mode === "add") for (const r of rows) if (!r.has) {
    const a = await gql(`mutation($i:ID!,$l:ID!,$key:String!){ inventoryActivate(inventoryItemId:$i, locationId:$l) @idempotent(key:$key){ userErrors{ message } } }`, { i: r.item, l: loc, key: crypto.randomUUID() });
    const e = a.inventoryActivate.userErrors; if (e?.length) throw new Error(`${r.title}: ${e[0].message}`);
  }
  const ref = `indifeels://stock-${mode}/` + crypto.randomUUID();
  let done = 0;
  for (const part of chunk(rows, 100)) {
    const m = await gql(`mutation($input: InventoryAdjustQuantitiesInput!, $key: String!){ inventoryAdjustQuantities(input:$input) @idempotent(key:$key){ inventoryAdjustmentGroup{ id } userErrors{ message } } }`,
      { key: crypto.randomUUID(), input: { name: "available", reason: "correction", referenceDocumentUri: ref,
        changes: part.map((r) => ({ inventoryItemId: r.item, locationId: loc, delta: sign * r.qty, changeFromQuantity: r.has ? r.cur : 0 })) } });
    const ue = m.inventoryAdjustQuantities.userErrors;
    if (ue?.length) return json({ error: `Updated ${done} of ${rows.length} variants, then Shopify stopped: ${ue[0].message}. Check the stock and try the rest again.`, updated: done }, 500);
    done += part.length;
  }
  const box = /^[A-Za-z0-9._-]{1,40}$/.test(String(body.box || "")) ? String(body.box) : "";
  let logWarn = "";
  try {   // history of separate add / remove changes (never blocks the stock change itself)
    const ln = loc === SHOPLOC ? "Shop location" : loc === BACKUP ? "Backup" : "";
    const lg = await svc.from("stock_adjustments").insert(rows.map((r) => ({ vid: r.vid, product: r.title.slice(0, 200), variant: "", loc: loc.split("/").pop(), loc_name: ln, mode, qty: r.qty, before_qty: r.cur, after_qty: Math.max(0, r.cur + sign * r.qty), by_name: by.slice(0, 80), box_no: box })));
    if (lg.error) logWarn = "Stock was updated, but the stock log could not be saved: " + lg.error.message.slice(0, 120);
  } catch (e) { logWarn = "Stock was updated, but the stock log could not be saved: " + String((e as Error)?.message || e).slice(0, 120); }
  const k = loc === SHOPLOC ? "melbourne_stock" : loc === BACKUP ? "storage_stock" : "";
  let warn = logWarn;
  if (k) {
    const mfs = rows.map((r) => ({ ownerId: `gid://shopify/ProductVariant/${r.vid}`, namespace: "custom", key: k, type: "number_integer", value: String(Math.max(0, r.cur + sign * r.qty)) }));
    for (const part of chunk(mfs, 25)) {
      const mf = await gql(`mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{ message } } }`, { m: part });
      const me = mf.metafieldsSet.userErrors;
      if (me?.length) { warn = (warn ? warn + " " : "") + "Stock updated, but the website ST number didn't update for some items: " + me[0].message; break; }
    }
  }
  return json({ ok: true, mode, variants: rows.length, units: rows.reduce((a, r) => a + r.qty, 0), ...(warn ? { warn } : {}) });
}

async function setBarcode(body: any) {
  const vid = String(body.vid || ""), bc = String(body.barcode || "").trim();
  if (!VID.test(vid)) return json({ error: "Bad variant" }, 400);
  if (!/^[0-9A-Za-z._-]{3,40}$/.test(bc)) return json({ error: "Barcode must be 3 to 40 letters or numbers" }, 400);
  const d = await gql(`query($id:ID!){ productVariant(id:$id){ id barcode product{ id } } }`, { id: `gid://shopify/ProductVariant/${vid}` });
  const v = d.productVariant; if (!v) return json({ error: "Variant not found" }, 404);
  if (v.barcode && v.barcode !== bc) return json({ error: "This variant already has a barcode (" + v.barcode + ")" }, 400);
  const dup = await gql(`query($q:String!){ productVariants(first:2, query:$q){ nodes{ id } } }`, { q: `barcode:${bc}` });
  if (dup.productVariants.nodes.some((n: any) => n.id !== v.id)) return json({ error: "Another variant already uses this barcode" }, 400);
  const m = await gql(`mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkUpdate(productId:$p, variants:$v){ userErrors{ message } } }`, { p: v.product.id, v: [{ id: v.id, barcode: bc }] });
  const ue = m.productVariantsBulkUpdate.userErrors; if (ue?.length) return json({ error: ue[0].message }, 400);
  return json({ ok: true, vid, barcode: bc });
}

async function createVariant(body: any) {
  const pid = String(body.pid || ""), title = String(body.title || "").trim().slice(0, 100), bc = String(body.barcode || "").trim();
  if (!VID.test(pid) || !title) return json({ error: "Bad product or size" }, 400);
  if (bc && !/^[0-9A-Za-z._-]{3,40}$/.test(bc)) return json({ error: "Barcode must be 3 to 40 letters or numbers" }, 400);
  const d = await gql(`query($id:ID!){ product(id:$id){ id options{ name } variants(first:100){ nodes{ id title price compareAtPrice selectedOptions{ name value } } } } }`, { id: `gid://shopify/Product/${pid}` });
  const p = d.product; if (!p) return json({ error: "Product not found on Shopify" }, 404);
  const nodes = p.variants.nodes;
  if (nodes.some((n: any) => n.title.trim().toLowerCase() === title.toLowerCase())) return json({ error: "That size already exists on this product" }, 400);
  const names = p.options.map((o: any) => o.name), parts = title.split(" / ").map((x) => x.trim());
  if (parts.length !== names.length) return json({ error: `This product has ${names.length} option(s) (${names.join(", ")}) so "${title}" can't be created automatically` }, 400);
  if (bc) {
    const dup = await gql(`query($q:String!){ productVariants(first:1, query:$q){ nodes{ id } } }`, { q: `barcode:${bc}` });
    if (dup.productVariants.nodes.length) return json({ error: "Another variant already uses this barcode" }, 400);
  }
  const base = nodes[0] || {};
  const v: any = { optionValues: parts.map((name, i) => ({ optionName: names[i], name })), price: base.price || "0.00", inventoryItem: { tracked: true } };
  if (base.compareAtPrice) v.compareAtPrice = base.compareAtPrice;
  if (bc) v.barcode = bc;
  const m = await gql(`mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkCreate(productId:$p, variants:$v){ productVariants{ id title barcode } userErrors{ message } } }`, { p: p.id, v: [v] });
  const ue = m.productVariantsBulkCreate.userErrors; if (ue?.length) return json({ error: ue[0].message }, 400);
  const nv = m.productVariantsBulkCreate.productVariants[0];
  return json({ ok: true, vid: nv.id.split("/").pop(), title: nv.title, barcode: nv.barcode || "", price: v.price });
}

// Live sizes of one product (so a size added after the last report refresh still shows up on the Barcodes page)
async function productVariants(body: any) {
  const pid = String(body.pid || "");
  if (!VID.test(pid)) return json({ error: "Bad product" }, 400);
  const d = await gql(`query($id:ID!){ product(id:$id){ id variants(first:100){ nodes{ id title price barcode inventoryItem{ inventoryLevels(first:10){ nodes{ location{ id } quantities(names:["available"]){ quantity } } } } } } } }`, { id: `gid://shopify/Product/${pid}` });
  if (!d.product) return json({ error: "Product not found" }, 404);
  const rows = d.product.variants.nodes.map((n: any) => {
    const qy: Record<string, number> = {};
    (n.inventoryItem?.inventoryLevels?.nodes || []).forEach((l: any) => { qy[String(l.location.id).split("/").pop()!] = q(l); });
    return { vid: String(n.id).split("/").pop(), title: n.title, price: n.price, barcode: n.barcode || "", q: qy };
  });
  return json({ ok: true, pid, variants: rows });
}

// Current name / price / photo / barcode of variants straight from Shopify, so labels reflect edits made after they were queued
async function labelInfo(body: any, svc: any) {
  const want = items(body, 200, 1000);
  const out: any[] = [];
  for (const ids of chunk([...want.keys()], 50)) {
    const d = await gql(`query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant{ id title price barcode product{ title featuredMedia{ preview{ image{ url } } } } } } }`, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`) });
    d.nodes.forEach((n: any) => { if (!n) return; out.push({ vid: String(n.id).split("/").pop(), product: n.product?.title || "", variant: n.title || "", barcode: n.barcode || "", price: n.price || "", image: n.product?.featuredMedia?.preview?.image?.url || "" }); });
  }
  await Promise.all(out.filter((r) => r.barcode).map((r) => svc.from("label_queue").update({ product: r.product, variant: r.variant, barcode: r.barcode }).eq("vid", r.vid).is("printed_at", null)));
  return json({ ok: true, rows: out });
}

// Latest changes since a date/time: (1) products created or published since then, (2) stock ADDED since then (net of removals) from the stock log.
async function latest(body: any, svc: any) {
  const t = Date.parse(String(body.since || ""));
  if (!Number.isFinite(t) || t > Date.now() + 86400000) return json({ error: "Bad date or time" }, 400);
  const since = new Date(t).toISOString(), sq = since.slice(0, 19) + "Z";
  const pid = (g: string) => String(g).split("/").pop()!;
  const img = (n: any) => n?.featuredMedia?.preview?.image?.url || "";
  // 1) new or newly published, active products (read live, so no report rebuild is needed)
  const NQ = `query($q:String!,$after:String){ products(first:10, after:$after, query:$q, sortKey:CREATED_AT, reverse:true){ pageInfo{ hasNextPage endCursor } nodes{ id title status createdAt publishedAt featuredMedia{ preview{ image{ url } } } variantsCount{ count } variants(first:40){ nodes{ id title price barcode inventoryQuantity } } } } }`;
  const news = new Map<string, any>();
  for (const f of ["created_at", "published_at"]) {
    let after: string | null = null;
    for (let pg = 0; pg < 4; pg++) {
      const d: any = await gql(NQ, { q: `${f}:>=${sq} AND status:active`, after });
      for (const n of d.products.nodes) {
        if (n.status !== "ACTIVE" || news.has(pid(n.id))) continue;
        const ok = (Date.parse(n.createdAt) >= t) || (n.publishedAt && Date.parse(n.publishedAt) >= t);
        if (!ok) continue;
        news.set(pid(n.id), { pid: pid(n.id), title: n.title, image: img(n), createdAt: n.createdAt, publishedAt: n.publishedAt || "", more: (n.variantsCount?.count || 0) > n.variants.nodes.length,
          variants: n.variants.nodes.map((v: any) => ({ vid: pid(v.id), title: v.title, price: v.price, barcode: v.barcode || "", qty: Math.max(0, Number(v.inventoryQuantity) || 0) })) });
      }
      if (!d.products.pageInfo.hasNextPage) break;
      after = d.products.pageInfo.endCursor;
    }
  }
  // 2) stock added through the app since then (Add / remove tab and box receiving), net of removals
  const { data: adj, error } = await svc.from("stock_adjustments").select("vid,qty,mode,box_no,created_at").gte("created_at", since).order("created_at", { ascending: false }).limit(3000);
  if (error) throw new Error(error.message);
  const net = new Map<string, { n: number; at: string; box: Set<string> }>();
  for (const r of adj || []) {
    const e = net.get(String(r.vid)) || { n: 0, at: "", box: new Set<string>() };
    e.n += (r.mode === "remove" ? -1 : 1) * (Number(r.qty) || 0);
    if (!e.at || r.created_at > e.at) e.at = r.created_at;
    if (r.box_no && r.mode !== "remove") e.box.add(String(r.box_no));
    net.set(String(r.vid), e);
  }
  // 2b) stock added DIRECTLY in Shopify (admin / POS), read from Shopify's own inventory history. App changes use reason "correction", so they are skipped here (already in the app log above).
  const shopifyVids = new Set<string>(); let shopifyWarn = "";
  try {
    const days = Math.min(60, Math.ceil((Date.now() - t) / 86400000) + 1), hourFloor = Math.floor(t / 3600000) * 3600000;
    const sd: any = await gql(`query($q:String!){ shopifyqlQuery(query:$q){ parseErrors tableData{ columns{ name } rows } } }`,
      { q: `FROM inventory_adjustment_history SHOW inventory_adjustment_change GROUP BY product_variant_id, inventory_change_reason, hour SINCE startOfDay(-${days}d) UNTIL today LIMIT 1000` });
    const res = sd.shopifyqlQuery;
    if (res?.parseErrors?.length) throw new Error(JSON.stringify(res.parseErrors).slice(0, 120));
    const cols = (res?.tableData?.columns || []).map((c: any) => c.name);
    const ix = (n: string) => cols.indexOf(n);
    for (const row of res?.tableData?.rows || []) {
      const o = Array.isArray(row) ? { v: row[ix("product_variant_id")], r: row[ix("inventory_change_reason")], h: row[ix("hour")], c: row[ix("inventory_adjustment_change")] }
        : { v: row.product_variant_id, r: row.inventory_change_reason, h: row.hour, c: row.inventory_adjustment_change };
      const c = Number(o.c) || 0, ht = Date.parse(String(o.h));
      if (c <= 0 || !o.v || !Number.isFinite(ht) || ht < hourFloor) continue;
      if (!["manual_adjustment", "initial_adjustment", "received"].includes(String(o.r))) continue;
      const v = String(o.v).split("/").pop()!, e = net.get(v) || { n: 0, at: "", box: new Set<string>() };
      e.n += c; const at = new Date(ht).toISOString(); if (!e.at || at > e.at) e.at = at;
      net.set(v, e); shopifyVids.add(v);
    }
  } catch (e) { shopifyWarn = "Could not read Shopify's own stock history: " + String((e as Error)?.message || e).slice(0, 140); }
  const vids = [...net.entries()].filter(([, e]) => e.n > 0).map(([v]) => v);
  const groups = new Map<string, any>();
  for (const ids of chunk(vids, 50)) {
    const d = await gql(`query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant{ id title price barcode product{ id title featuredMedia{ preview{ image{ url } } } } } } }`, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`) });
    d.nodes.forEach((n: any) => {
      if (!n?.product) return;
      const p = pid(n.product.id); if (news.has(p)) return;   // a new product already prints its full stock
      const e = net.get(pid(n.id))!;
      const g = groups.get(p) || { pid: p, title: n.product.title, image: img(n.product), at: "", variants: [] };
      g.variants.push({ vid: pid(n.id), title: n.title, price: n.price, barcode: n.barcode || "", added: e.n, box: [...e.box].join(", "), at: e.at, shopify: shopifyVids.has(pid(n.id)) });
      if (!g.at || e.at > g.at) g.at = e.at;
      groups.set(p, g);
    });
  }
  const added = [...groups.values()].sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return json({ ok: true, since, news: [...news.values()], added, ...(shopifyWarn ? { warn: shopifyWarn } : {}) });
}

async function setStatus(body: any) {
  const pid = String(body.pid || ""), st = body.status === "UNLISTED" ? "UNLISTED" : "ACTIVE";
  if (!VID.test(pid)) return json({ error: "Bad product" }, 400);
  const m = await gql(`mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id status onlineStoreUrl } userErrors{ message } } }`, { p: { id: `gid://shopify/Product/${pid}`, status: st } });
  const ue = m.productUpdate.userErrors; if (ue?.length) return json({ error: ue[0].message }, 400);
  const p = m.productUpdate.product;
  return json({ ok: true, pid, status: p.status, url: p.onlineStoreUrl || "", channels: null });
}

// Delete ONE variant that shares its barcode with another variant. Refuses if it is not a duplicate or still holds stock.
async function deleteVariant(body: any) {
  const vid = String(body.vid || "");
  if (!VID.test(vid)) return json({ error: "Bad variant" }, 400);
  const d = await gql(`query($id:ID!){ productVariant(id:$id){ id title barcode product{ id title variantsCount{ count } } inventoryItem{ inventoryLevels(first:20){ nodes{ quantities(names:["available"]){ quantity } } } } } }`, { id: `gid://shopify/ProductVariant/${vid}` });
  const v = d.productVariant; if (!v) return json({ error: "Variant not found (already deleted?)" }, 404);
  if (!v.barcode) return json({ error: "Only variants with a duplicated barcode can be deleted here" }, 400);
  const dup = await gql(`query($q:String!){ productVariants(first:5, query:$q){ nodes{ id } } }`, { q: `barcode:${v.barcode}` });
  if (!dup.productVariants.nodes.some((n: any) => n.id !== v.id)) return json({ error: "This is the only variant with that barcode, so it is not a duplicate" }, 400);
  if ((v.product?.variantsCount?.count ?? 0) < 2) return json({ error: "It is the only variant of its product" }, 400);
  const units = (v.inventoryItem?.inventoryLevels?.nodes || []).reduce((a: number, l: any) => a + q(l), 0);
  if (units > 0) return json({ error: `${v.product.title} ${v.title} still has ${units} in stock. Move it to the other variant first.` }, 400);
  const m = await gql(`mutation($p:ID!,$v:[ID!]!){ productVariantsBulkDelete(productId:$p, variantsIds:$v){ userErrors{ message } } }`, { p: v.product.id, v: [v.id] });
  const ue = m.productVariantsBulkDelete.userErrors; if (ue?.length) return json({ error: ue[0].message }, 400);
  return json({ ok: true, vid, name: `${v.product.title} ${v.title}` });
}

async function labelQueue(body: any, svc: any) {
  const op = String(body.op || "list");
  if (op === "setcopies") {
    const want = items(body, 200, 5000);
    for (const [vid, n] of want) { const { error } = await svc.from("label_queue").update({ copies: n }).eq("vid", vid).is("printed_at", null); if (error) throw new Error(error.message); }
    return json({ ok: true });
  }
  if (op === "remove") {
    const want = items(body, 200, 5000);
    const { error } = await svc.from("label_queue").delete().in("vid", [...want.keys()]).is("printed_at", null);
    if (error) throw new Error(error.message);
    return json({ ok: true });
  }
  if (op === "list") {
    const { data, error } = await svc.from("label_queue").select("id,vid,product,variant,barcode,copies,created_at").is("printed_at", null).order("created_at", { ascending: true }).limit(2000);
    if (error) throw new Error(error.message);
    return json({ ok: true, rows: data || [] });
  }
  if (op === "done") {
    const { error } = await svc.from("label_queue").update({ printed_at: new Date().toISOString() }).is("printed_at", null);
    if (error) throw new Error(error.message);
    return json({ ok: true });
  }
  if (op === "add") {
    const want = items(body, 200, 500);
    if (!want.size) return json({ error: "Nothing to queue" }, 400);
    const out: any[] = [], noBc: string[] = [];
    for (const ids of chunk([...want.keys()], 50)) {
      const d = await gql(`query($ids:[ID!]!){ nodes(ids:$ids){ ... on ProductVariant{ id title barcode product{ title } } } }`, { ids: ids.map((i) => `gid://shopify/ProductVariant/${i}`) });
      d.nodes.forEach((n: any) => {
        if (!n) return;
        const vid = n.id.split("/").pop(), title = `${n.product?.title || ""} ${n.title || ""}`.trim();
        if (!n.barcode) { noBc.push(title); return; }
        out.push({ vid, product: n.product?.title || "", variant: n.title || "", barcode: n.barcode, copies: want.get(vid)! });
      });
    }
    if (noBc.length) return json({ error: "These have no barcode yet: " + noBc.slice(0, 5).join("; ") }, 400);
    for (const r of out) {
      const { data: ex } = await svc.from("label_queue").select("id,copies").eq("vid", r.vid).is("printed_at", null).maybeSingle();
      const res = ex ? await svc.from("label_queue").update({ copies: ex.copies + r.copies }).eq("id", ex.id) : await svc.from("label_queue").insert(r);
      if (res.error) throw new Error(res.error.message);
    }
    return json({ ok: true, queued: out.length });
  }
  return json({ error: "Unknown label action" }, 400);
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);
  const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const bearer = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const { data: who, error: whoErr } = await svc.auth.getUser(bearer);
  if (whoErr || !who?.user) return json({ error: "Not signed in" }, 401);
  const { data: prof } = await svc.from("profiles").select("is_admin,disabled,display_name,username").eq("id", who.user.id).single();
  if (!prof || prof.disabled || !prof.is_admin) return json({ error: "Only the owner can change stock" }, 403);
  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  try {
    if (body.action === "adjustlist") return await adjustList(body, svc, String(prof.display_name || prof.username || ""));
    if (body.action === "setbarcode") return await setBarcode(body);
    if (body.action === "createvariant") return await createVariant(body);
    if (body.action === "productvariants") return await productVariants(body);
    if (body.action === "labelinfo") return await labelInfo(body, svc);
    if (body.action === "latest") return await latest(body, svc);
    if (body.action === "setstatus") return await setStatus(body);
    if (body.action === "deletevariant") return await deleteVariant(body);
    if (body.action === "labelqueue") return await labelQueue(body, svc);
    return json({ error: "Unknown action" }, 400);
  } catch (e) {
    return json({ error: String((e as Error)?.message || e).slice(0, 300) }, 500);
  }
});
