import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

// Nightly stock snapshot -> table inventory_snapshots (one row per variant per Melbourne day).
// Called by pg_cron with the x-schedule-token header (same pattern as board-notify / report-scheduler).
// Total available stock across all locations (inventoryQuantity). Idempotent: re-running a day overwrites that day.
const SHOP = Deno.env.get("SHOPIFY_SHOP") || "bvdxj3-r8.myshopify.com";
const API = `https://${SHOP}/admin/api/2026-04/graphql.json`;
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });

async function gql(query: string, variables: Record<string, unknown>) {
  const token = Deno.env.get("SHOPIFY_TOKEN") ?? "";
  if (!token) throw new Error("SHOPIFY_TOKEN is not set on the Supabase function");
  for (let a = 0; a < 4; a++) {
    const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": token }, body: JSON.stringify({ query, variables }) });
    if ((r.status === 429 || r.status >= 500) && a < 3) { await new Promise((x) => setTimeout(x, 1500 * (a + 1))); continue; }
    if (!r.ok) throw new Error(`Shopify returned HTTP ${r.status}`);
    const o = await r.json();
    if (o.errors) {
      if (JSON.stringify(o.errors).includes("THROTTLED") && a < 3) { await new Promise((x) => setTimeout(x, 2000)); continue; }
      throw new Error("Shopify: " + JSON.stringify(o.errors).slice(0, 200));
    }
    return o.data;
  }
  throw new Error("Shopify kept throttling");
}

const tail = (gid: string) => Number(String(gid).split("/").pop());

Deno.serve(async (req) => {
  const svc = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: secret, error } = await svc.rpc("report_scheduler_secret");
  if (error || !secret || req.headers.get("x-schedule-token") !== secret) return json({ error: "Not authorized" }, 401);

  // Melbourne calendar day the snapshot belongs to.
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Australia/Melbourne" }).format(new Date());
  const rows: { snap_date: string; product_id: number; variant_id: number; qty: number }[] = [];
  const Q = `query($after:String){ products(first:50, after:$after, query:"status:active"){ pageInfo{hasNextPage endCursor}
    nodes{ id variants(first:100){ nodes{ id inventoryQuantity } } } } }`;
  let after: string | null = null;
  try {
    for (let page = 0; page < 200; page++) {
      const d = await gql(Q, { after });
      for (const p of d.products.nodes) for (const v of p.variants.nodes)
        rows.push({ snap_date: day, product_id: tail(p.id), variant_id: tail(v.id), qty: v.inventoryQuantity ?? 0 });
      if (!d.products.pageInfo.hasNextPage) break;
      after = d.products.pageInfo.endCursor;
    }
    if (!rows.length) return json({ error: "Shopify returned no variants; nothing saved" }, 502);
    for (let i = 0; i < rows.length; i += 1000) {
      const { error: e } = await svc.from("inventory_snapshots").upsert(rows.slice(i, i + 1000), { onConflict: "snap_date,variant_id" });
      if (e) throw new Error("Save failed: " + e.message);
    }
    return json({ ok: true, day, variants: rows.length });
  } catch (e) {
    return json({ error: String((e as Error).message || e) }, 500);
  }
});
