import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Stock Take and Transfer -> "Add / remove" tab. Admin only.
//  adjustlist : add or remove pieces at ONE Shopify location for a list of variants (+ website ST metafield)
//  setbarcode : put a barcode on a variant that has none
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

async function adjustList(body: any) {
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
    const a = await gql(`mutation($i:ID!,$l:ID!){ inventoryActivate(inventoryItemId:$i, locationId:$l){ userErrors{ message } } }`, { i: r.item, l: loc });
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
  const k = loc === SHOPLOC ? "melbourne_stock" : loc === BACKUP ? "storage_stock" : "";
  let warn = "";
  if (k) {
    const mfs = rows.map((r) => ({ ownerId: `gid://shopify/ProductVariant/${r.vid}`, namespace: "custom", key: k, type: "number_integer", value: String(Math.max(0, r.cur + sign * r.qty)) }));
    for (const part of chunk(mfs, 25)) {
      const mf = await gql(`mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ userErrors{ message } } }`, { m: part });
      const me = mf.metafieldsSet.userErrors;
      if (me?.length) { warn = "Stock updated, but the website ST number didn't update for some items: " + me[0].message; break; }
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

async function labelQueue(body: any, svc: any) {
  const op = String(body.op || "list");
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
  const { data: prof } = await svc.from("profiles").select("is_admin,disabled").eq("id", who.user.id).single();
  if (!prof || prof.disabled || !prof.is_admin) return json({ error: "Only the owner can change stock" }, 403);
  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  try {
    if (body.action === "adjustlist") return await adjustList(body);
    if (body.action === "setbarcode") return await setBarcode(body);
    if (body.action === "labelqueue") return await labelQueue(body, svc);
    return json({ error: "Unknown action" }, 400);
  } catch (e) {
    return json({ error: String((e as Error)?.message || e).slice(0, 300) }, 500);
  }
});
