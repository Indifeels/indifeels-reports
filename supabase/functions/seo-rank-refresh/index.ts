import {createClient} from 'npm:@supabase/supabase-js@2.57.4';
const url=Deno.env.get('SUPABASE_URL')!;
const svc=createClient(url,Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,{auth:{persistSession:false}});
Deno.serve(async(req:Request)=>{
 const reply=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
 if(req.method!=='POST')return reply({error:'Use POST'},405);
 try{
  const body=await req.json();
  const token=body.token;
  if(typeof token!=='string'||!token)return reply({error:'Unauthorized'},401);
  // Reuse the existing server-side sync credential validation. Never return its files.
  const auth=await svc.rpc('sync_get_files',{p_token:token});
  if(auth.error)return reply({error:'Unauthorized'},401);
  if(body.mode==='export'){
   const {data,error}=await svc.from('seo_rank_products').select('category_id,handle,url,target_keyword');
   if(error)throw Error('Product read failed');
   return reply({products:data});
  }
  if(body.mode==='publish'){
   const {data,error}=await svc.rpc('publish_seo_rank_refresh',{p_snapshot:body.snapshot,p_through:body.through,p_rows:body.rows});
   if(error)throw Error('Publication failed: '+error.message);
   return reply(data);
  }
  return reply({error:'Unknown mode'},400);
 }catch(e){return reply({error:(e as Error).message},500);}
});