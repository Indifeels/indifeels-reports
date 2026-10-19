import webpush from "npm:web-push@3.6.7";
const url = Deno.env.get("SUPABASE_URL")!;
const svc = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const dbHeaders = { "apikey":svc, "Authorization":"Bearer "+svc, "Content-Type":"application/json" };
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status,headers:{"Content-Type":"application/json"}});
async function db(path: string, options: RequestInit = {}): Promise<any> {
  const r = await fetch(url + "/rest/v1/" + path, {...options, headers: {...dbHeaders,...(options.headers||{})}});
  if (!r.ok) throw new Error("Database HTTP " + r.status);
  const t = await r.text(); return t ? JSON.parse(t) : null;
}
function secureMatch(a: string, b: string) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i=0;i<a.length;i++) diff |= a.charCodeAt(i)^b.charCodeAt(i);
  return diff === 0;
}
Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return reply({ok:false,error:"Method not allowed"},405);
  try {
    const token = req.headers.get("x-parcel-token") || "";
    if (!/^[a-f0-9]{64}$/.test(token)) return reply({ok:false,error:"Unauthorized"},401);
    const rows = await db("parcel_box_notification_config?id=eq.1&select=webhook_secret");
    if (!rows?.length || !secureMatch(token,rows[0].webhook_secret)) return reply({ok:false,error:"Unauthorized"},401);
    const body = await req.json().catch(() => ({}));
    const raw = Array.isArray(body?.message_ids) ? body.message_ids : [];
    const ids: string[] = [...new Set(raw)].filter((id): id is string => typeof id === "string" && /^[a-f0-9]{16,20}$/.test(id)).slice(0,100);
    if (!ids.length) return reply({ok:false,error:"No valid Gmail message IDs"},400);
    const processed = await db("parcel_box_processed_emails?select=message_id&message_id=in.("+ids.join(",")+")");
    const known = new Set((processed||[]).map((o:any)=>o.message_id));
    const fresh = ids.filter(id=>!known.has(id));
    if (!fresh.length) return reply({ok:true,duplicate:true,sent:0});
    const subs = await db("push_subscriptions?enabled=eq.true&select=id,endpoint,p256dh,auth_key,origin,profiles!inner(is_admin,disabled)&profiles.is_admin=eq.true&profiles.disabled=eq.false");
    if (!subs?.length) return reply({ok:true,skipped:"no-admin-subscribers",sent:0});
    const vapid = await db("push_config?id=eq.1&select=public_key,private_key");
    if (!vapid?.length) throw new Error("Push keys missing");
    webpush.setVapidDetails("mailto:notifications@indifeels.com",vapid[0].public_key,vapid[0].private_key);
    let sent=0;
    for (const s of subs) {
      try {
        let origin = String(s.origin||"");
        if (origin.endsWith("/")) origin=origin.slice(0,-1);
        await webpush.sendNotification(
          {endpoint:s.endpoint, keys:{p256dh:s.p256dh,auth:s.auth_key}},
          JSON.stringify({title:"🚚 Parcel Box Cleared",body:" ",tag:"indifeels-parcel-box-cleared",url:origin+"/"}),
          {TTL:3600,urgency:"normal"});
        sent++;
      } catch (e:any) {
        const status=Number(e?.statusCode||e?.status||0);
        if(status===404||status===410) {
          await db("push_subscriptions?id=eq."+encodeURIComponent(String(s.id)),{
            method:"PATCH",headers:{Prefer:"return=minimal"},
            body:JSON.stringify({enabled:false,updated_at:new Date().toISOString()})
          }).catch(()=>{});
        }
      }
    }
    if(!sent) return reply({ok:false,error:"No devices accepted notification",sent:0},502);
    await db("parcel_box_processed_emails?on_conflict=message_id",{
      method:"POST",
      headers:{Prefer:"resolution=ignore-duplicates,return=minimal"},
      body:JSON.stringify(fresh.map(message_id=>({message_id})))
    });
    return reply({ok:true,sent,unique_messages:fresh.length});
  } catch(e:any) {return reply({ok:false,error:String(e?.message||e)},500);}
});