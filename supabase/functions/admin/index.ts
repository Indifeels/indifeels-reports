import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const DOMAIN = "users.indifeels.app"; // login usernames map to <username>@users.indifeels.app
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
const USER_RE = /^[a-z0-9._-]{3,32}$/;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "Use POST" }, 405);
  const url = Deno.env.get("SUPABASE_URL")!;
  const svc = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  // Identify caller from their JWT
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const { data: who, error: whoErr } = await svc.auth.getUser(token);
  if (whoErr || !who?.user) return json({ error: "Not signed in" }, 401);
  const { data: me } = await svc.from("profiles").select("is_admin,disabled").eq("id", who.user.id).single();
  if (!me?.is_admin || me.disabled) return json({ error: "Admins only" }, 403);

  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: "Bad request" }, 400); }
  const a = body.action;
  try {
    if (a === "list") {
      const [{ data: users }, { data: grants }, { data: reports }, { data: resets }, { data: categories }, { data: category_grants }] = await Promise.all([
        svc.from("profiles").select("id,username,display_name,email,is_admin,disabled,created_at").order("created_at"),
        svc.from("user_reports").select("user_id,report_id"),
        svc.from("reports").select("id,title,sort,category_id,admin_only").order("sort"),
        svc.from("reset_requests").select("id,username,note,created_at,handled_at").order("created_at", { ascending: false }).limit(50),
        svc.from("report_categories").select("*").order("sort"),
        svc.from("user_report_categories").select("user_id,category_id"),
      ]);
      return json({ users, grants, reports, resets, categories, category_grants });
    }
    if (a === "create") {
      const username = String(body.username || "").trim().toLowerCase();
      const password = String(body.password || "");
      if (!USER_RE.test(username)) return json({ error: "Username must be 3-32 characters: lowercase letters, numbers, dot, dash or underscore." }, 400);
      if (password.length < 8) return json({ error: "Password must be at least 8 characters." }, 400);
      const { data: exists } = await svc.from("profiles").select("id").eq("username", username).maybeSingle();
      if (exists) return json({ error: "That username is taken." }, 400);
      const { data: cu, error: ce } = await svc.auth.admin.createUser({ email: `${username}@${DOMAIN}`, password, email_confirm: true, user_metadata: { username } });
      if (ce) return json({ error: ce.message }, 400);
      const uid = cu.user!.id;
      const { error: pe } = await svc.from("profiles").insert({ id: uid, username, display_name: body.display_name || null, email: body.email || null, is_admin: !!body.is_admin });
      if (pe) { await svc.auth.admin.deleteUser(uid); return json({ error: pe.message }, 400); }
      const reps: string[] = Array.isArray(body.reports) ? body.reports : [];
      const { error: ge } = await svc.rpc("save_user_report_access", { target: uid, report_ids: reps, category_ids: body.category_ids || [] });
      if (ge) { await svc.auth.admin.deleteUser(uid); return json({error:ge.message},400); }
      return json({ ok: true, id: uid });
    }
    if (a === "update") {
      const id = String(body.id || "");
      if (!id) return json({ error: "Missing user" }, 400);
      const patch: Record<string, unknown> = {};
      for (const k of ["display_name", "email", "disabled", "is_admin"]) if (k in body) patch[k] = body[k];
      if (id === who.user.id && (patch.disabled === true || patch.is_admin === false)) return json({ error: "You can't disable or demote your own admin account." }, 400);
      if (Object.keys(patch).length) {
        const { error } = await svc.from("profiles").update(patch).eq("id", id);
        if (error) return json({ error: error.message }, 400);
        if ("disabled" in patch) await svc.auth.admin.updateUserById(id, { ban_duration: patch.disabled ? "876000h" : "none" });
      }
      if (Array.isArray(body.reports) || Array.isArray(body.category_ids)) {
        const {data: existing} = await svc.from("user_report_categories").select("category_id").eq("user_id",id);
        const {error} = await svc.rpc("save_user_report_access",{target:id,report_ids:body.reports || [],category_ids:body.category_ids || (existing || []).map((g:any)=>g.category_id)});
        if(error) return json({error:error.message},400);
      }
      return json({ ok: true });
    }
    if (a === "set_password") {
      const id = String(body.id || ""); const password = String(body.password || "");
      if (password.length < 8) return json({ error: "Password must be at least 8 characters." }, 400);
      const { error } = await svc.auth.admin.updateUserById(id, { password });
      if (error) return json({ error: error.message }, 400);
      return json({ ok: true });
    }
    if (a === "delete") {
      const id = String(body.id || "");
      if (id === who.user.id) return json({ error: "You can't delete your own account." }, 400);
      const { error } = await svc.auth.admin.deleteUser(id);
      if (error) return json({ error: error.message }, 400);
      return json({ ok: true });
    }
    if (a === "reset_handled") {
      const { error } = await svc.from("reset_requests").update({ handled_at: new Date().toISOString() }).eq("id", body.id);
      if (error) return json({ error: error.message }, 400);
      return json({ ok: true });
    }
    return json({ error: "Unknown action" }, 400);
  } catch (e) {
    return json({ error: String((e as Error)?.message || e) }, 500);
  }
});
