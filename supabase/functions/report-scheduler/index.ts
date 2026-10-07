import { createClient } from 'npm:@supabase/supabase-js@2.57.4';
const url=Deno.env.get('SUPABASE_URL')!;
const svc=createClient(url,Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,{auth:{persistSession:false}});
const repo='Indifeels/indifeels-reports';
const headers={'Content-Type':'application/json'};
const reply=(b:unknown,s=200)=>new Response(JSON.stringify(b),{status:s,headers});
async function gh(path:string,body?:unknown){
 const token=Deno.env.get('GITHUB_DISPATCH_TOKEN');
 if(!token)throw Error('GitHub dispatch credential is missing');
 const r=await fetch('https://api.github.com/repos/'+repo+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json','Content-Type':'application/json','User-Agent':'IndiFeels-Schedule-Panel'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
 if(!r.ok)throw Error('GitHub returned HTTP '+r.status);
 return r.status===204?null:await r.json();
}
async function patch(id:string,value:Record<string,unknown>){const {error}=await svc.from('report_refresh_runs').update(value).eq('id',id);if(error)throw Error('Could not update refresh status');}
async function tick(){
 const {data:active,error:ae}=await svc.from('report_refresh_runs').select('*').in('status',['queued','in_progress']).not('schedule_group','is',null);
 if(ae)throw Error('Could not read active refreshes');
 const groups=new Map<string,any[]>();
 for(const r of active||[])if(Date.now()-Date.parse(r.scheduled_at)>2*3600000){await patch(r.id,{status:'failed',finished_at:new Date().toISOString(),detail:'Refresh exceeded the 2 hour execution window. Check the runner.'});}
 for(const r of active||[])if(r.runner?.endsWith('.yml')&&Date.now()-Date.parse(r.scheduled_at)<=2*3600000){const k=r.runner;if(!groups.has(k))groups.set(k,[]);groups.get(k)!.push(r);}
 // Match the exact named dispatch, never another successful or skipped workflow.
 for(const [workflow,runs] of groups){
  try{
   const listing=await gh('/actions/workflows/'+encodeURIComponent(workflow)+'/runs?event=repository_dispatch&per_page=100');
   for(const run of runs){
    const hit=(listing.workflow_runs||[]).find((x:any)=>x.display_title==='Schedule '+run.schedule_group);
    if(hit){
     if(hit.status==='completed')await patch(run.id,{status:hit.conclusion==='success'?'completed':'failed',started_at:hit.run_started_at,finished_at:hit.updated_at,github_run_id:hit.id,detail:hit.conclusion==='success'?'Report refresh finished.':'GitHub refresh '+String(hit.conclusion)+'. Open Actions for details.'});
     else if(hit.status==='in_progress')await patch(run.id,{status:'in_progress',started_at:hit.run_started_at,github_run_id:hit.id,detail:'Building and publishing report'});
    }else if(Date.now()-Date.parse(run.scheduled_at)>2*3600000)await patch(run.id,{status:'failed',finished_at:new Date().toISOString(),detail:'No matching GitHub run within 2 hours. Check dispatch access and workflow configuration.'});
   }
  }catch{ /* Keep status unchanged during a transient read failure; the execution timeout remains enforced. */ }
 }
 const {data:due,error}=await svc.rpc('claim_report_refreshes');
 if(error)throw Error('Could not claim due schedules');
 let dispatched=0,failed=0;
 const batches=new Map<string,any[]>();
 for(const row of due||[]){
  if(!row.runner){await patch(row.id,{status:'failed',finished_at:new Date().toISOString(),detail:'No automated data refresh runner is connected for this report.'});failed++;continue;}
  if(!batches.has(row.runner))batches.set(row.runner,[]);batches.get(row.runner)!.push(row);
 }
 for(const [runner,runs] of batches){
  const group=crypto.randomUUID();
  for(const r of runs)await patch(r.id,{schedule_group:group});
  try{
   if(runner==='native:tech-availability-monitor'){
    for(const r of runs)await patch(r.id,{status:'in_progress',started_at:new Date().toISOString()});
    const res=await fetch(url+'/functions/v1/tech-availability-monitor',{method:'POST',signal:AbortSignal.timeout(100000)});
    const data=await res.json();if(!res.ok||!data.ok)throw Error('Availability monitor failed');
    for(const r of runs)await patch(r.id,{status:'completed',finished_at:new Date().toISOString(),detail:data.skipped?'Recent verified monitor data retained':'Availability data refreshed'});
   }else{
    await gh('/dispatches',{event_type:'report-schedule',client_payload:{schedule_group:group,report_ids:runs.map(r=>r.report_id),schedule_run_ids:runs.map(r=>r.id)}});
   }
   dispatched+=runs.length;
  }catch(e){for(const r of runs)await patch(r.id,{status:'failed',finished_at:new Date().toISOString(),detail:(e as Error).message.slice(0,240)});failed+=runs.length;}
 }
 await svc.rpc('prune_report_refresh_runs');
 return {ok:true,dispatched,failed,checked_at:new Date().toISOString()};
}
Deno.serve(async(req:Request)=>{
 if(req.method!=='POST')return reply({error:'Use POST'},405);
 const {data:secret,error}=await svc.rpc('report_scheduler_secret');
 if(error||!secret||req.headers.get('x-schedule-token')!==secret)return reply({error:'Not authorized'},401);
 try{return reply(await tick());}catch{return reply({error:'Schedule check failed; inspect scheduler logs'},500);}
});
