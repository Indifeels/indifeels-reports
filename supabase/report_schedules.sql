-- Shared per-report schedule authority. No credentials are stored in public tables.
create schema if not exists report_private;
revoke all on schema report_private from public,anon,authenticated;
create table if not exists report_private.scheduler_secret (id boolean primary key default true check(id), secret text not null);
insert into report_private.scheduler_secret(id,secret) values(true,encode(gen_random_bytes(32),'hex')) on conflict do nothing;

create table public.report_refresh_control (
 report_id text primary key references public.reports(id) on delete cascade,
 enabled boolean not null default true, time_enabled boolean not null default true,
 trigger_enabled boolean not null default true, runner text, runner_note text,
 updated_at timestamptz not null default now()
);
create table public.report_schedules (
 id uuid primary key default gen_random_uuid(),report_id text not null references public.reports(id) on delete cascade,
 kind text not null check(kind in ('time','trigger')), enabled boolean not null default true,
 frequency text check(frequency in ('daily','weekly','fortnightly','monthly','quarterly','yearly','interval')),
 start_date date not null default current_date,start_time time not null default '06:00',weekday integer check(weekday between 0 and 6),
 interval_minutes integer check(interval_minutes between 5 and 1440),
 trigger_event text check(trigger_event in ('new_order','source_sync')),
 next_at timestamptz,created_at timestamptz not null default now(),
 check ((kind='time' and frequency is not null and trigger_event is null) or (kind='trigger' and trigger_event is not null and frequency is null)),
 check(frequency is distinct from 'weekly' or weekday is not null),
 check(frequency is distinct from 'interval' or interval_minutes is not null)
);
create index report_schedule_due on public.report_schedules(next_at) where enabled and kind='time';
create table public.report_refresh_runs (
 id uuid primary key default gen_random_uuid(),report_id text not null references public.reports(id),
 schedule_id uuid references public.report_schedules(id) on delete set null,
 schedule_group text,runner text,scheduled_at timestamptz not null,
 started_at timestamptz,finished_at timestamptz,status text not null default 'queued' check(status in ('queued','in_progress','completed','failed')),
 origin text not null default 'time',detail text,github_run_id bigint,
 unique(schedule_id,scheduled_at)
);
create index report_run_recent on public.report_refresh_runs(report_id,scheduled_at desc);
create table public.report_refresh_events(id bigint generated always as identity primary key,event text not null check(event in ('new_order','source_sync')),created_at timestamptz not null default now(),processed boolean not null default false);
alter table public.report_refresh_control enable row level security;
alter table public.report_schedules enable row level security;
alter table public.report_refresh_runs enable row level security;
alter table public.report_refresh_events enable row level security;
grant select on public.report_refresh_control,public.report_schedules,public.report_refresh_runs to authenticated;
grant select,insert,update,delete on public.report_refresh_control,public.report_schedules,public.report_refresh_runs,public.report_refresh_events to service_role;
grant usage,select on sequence public.report_refresh_events_id_seq to service_role;
create policy control_read on public.report_refresh_control for select to authenticated using(public.can_view(report_id));
create policy schedules_read on public.report_schedules for select to authenticated using(public.can_view(report_id));
create policy runs_read on public.report_refresh_runs for select to authenticated using(public.can_view(report_id));
grant insert,update,delete on public.report_schedules to authenticated;
grant insert,update on public.report_refresh_control to authenticated;
create policy schedules_admin on public.report_schedules for all to authenticated using(public.is_admin()) with check(public.is_admin());
create policy control_admin on public.report_refresh_control for all to authenticated using(public.is_admin()) with check(public.is_admin());

create or replace function public.report_next_refresh(f text,d date,t time,w integer,a timestamptz,mins integer default null)
returns timestamptz language plpgsql stable security invoker set search_path=pg_catalog as $$
declare day date;candidate timestamptz;local_after date;month_delta integer;lastday integer;desired integer;
begin
 if f='interval' then return to_timestamp((floor(extract(epoch from a)/(mins*60))+1)*(mins*60));end if;
 local_after:=(a at time zone 'Australia/Melbourne')::date;
 for i in 0..1500 loop
  day:=greatest(d,local_after)+i;
  month_delta:=(extract(year from day)::integer-extract(year from d)::integer)*12+extract(month from day)::integer-extract(month from d)::integer;
  lastday:=extract(day from (date_trunc('month',day)+interval '1 month - 1 day'))::integer;
  desired:=least(extract(day from d)::integer,lastday);
  if (f='daily') or (f='weekly' and extract(dow from day)::integer=w) or
   (f='fortnightly' and (day-d)%14=0) or
   (f='monthly' and extract(day from day)::integer=desired) or
   (f='quarterly' and month_delta%3=0 and extract(day from day)::integer=desired) or
   (f='yearly' and month_delta%12=0 and extract(day from day)::integer=desired) then
   candidate:=(day+t) at time zone 'Australia/Melbourne';
   if candidate>a then return candidate;end if;
  end if;
 end loop;
 raise exception 'Could not compute next refresh';
end;$$;
revoke all on function public.report_next_refresh(text,date,time,integer,timestamptz,integer) from public,anon;
grant execute on function public.report_next_refresh(text,date,time,integer,timestamptz,integer) to authenticated,service_role;

create or replace function public.save_report_schedules(p_report text,p_control jsonb,p_schedules jsonb)
returns void language plpgsql security invoker set search_path=public,pg_catalog as $$
declare s jsonb;sid uuid;d date;t time;f text;w integer;m integer;
begin
 if not public.is_admin() then raise exception 'Only admins can change schedules';end if;
 if p_report='schedule-panel' or not exists(select 1 from public.reports where id=p_report) then raise exception 'Unknown report';end if;
 if jsonb_typeof(p_schedules)<>'array' or jsonb_array_length(p_schedules)>30 then raise exception 'Use at most 30 schedules';end if;
 insert into public.report_refresh_control(report_id,enabled,time_enabled,trigger_enabled) values(p_report,(p_control->>'enabled')::boolean,(p_control->>'time_enabled')::boolean,(p_control->>'trigger_enabled')::boolean)
 on conflict(report_id) do update set enabled=excluded.enabled,time_enabled=excluded.time_enabled,trigger_enabled=excluded.trigger_enabled,updated_at=now();
 delete from public.report_schedules where report_id=p_report and not exists(select 1 from jsonb_array_elements(p_schedules) x where x->>'id'=report_schedules.id::text);
 for s in select * from jsonb_array_elements(p_schedules) loop
  sid:=coalesce(nullif(s->>'id','')::uuid,gen_random_uuid());
  if exists(select 1 from public.report_schedules where id=sid and report_id<>p_report) then raise exception 'Schedule belongs to another report';end if;
  d:=coalesce((s->>'start_date')::date,(now() at time zone 'Australia/Melbourne')::date);
  t:=coalesce((s->>'start_time')::time,'06:00'::time);f:=s->>'frequency';w:=(s->>'weekday')::integer;m:=(s->>'interval_minutes')::integer;
  insert into public.report_schedules(id,report_id,kind,enabled,frequency,start_date,start_time,weekday,interval_minutes,trigger_event,next_at)
  values(sid,p_report,s->>'kind',coalesce((s->>'enabled')::boolean,true),f,d,t,w,m,s->>'trigger_event',case when s->>'kind'='time' then public.report_next_refresh(f,d,t,w,now(),m) end)
  on conflict(id) do update set kind=excluded.kind,enabled=excluded.enabled,frequency=excluded.frequency,start_date=excluded.start_date,start_time=excluded.start_time,weekday=excluded.weekday,interval_minutes=excluded.interval_minutes,trigger_event=excluded.trigger_event,next_at=excluded.next_at;
 end loop;
end;$$;
revoke all on function public.save_report_schedules(text,jsonb,jsonb) from public,anon;
grant execute on function public.save_report_schedules(text,jsonb,jsonb) to authenticated;

-- Service-only RPCs are used by the authenticated scheduler, never by public clients.
create or replace function public.report_scheduler_secret() returns text language sql security definer set search_path=pg_catalog as $$select secret from report_private.scheduler_secret where id$$;
revoke all on function public.report_scheduler_secret() from public,anon,authenticated;
grant execute on function public.report_scheduler_secret() to service_role;
create or replace function public.claim_report_refreshes() returns setof public.report_refresh_runs
language plpgsql security invoker set search_path=public,pg_catalog as $$
declare job record;ev record;stamp timestamptz:=now();
begin
 if not pg_try_advisory_xact_lock(74612081) then return;end if;
 for job in select s.*,c.runner from public.report_schedules s join public.report_refresh_control c using(report_id)
 where s.kind='time' and s.enabled and c.enabled and c.time_enabled and s.next_at<=stamp
 and not exists(select 1 from public.report_refresh_runs r where r.report_id=s.report_id and r.status in ('queued','in_progress')) for update of s loop
  insert into public.report_refresh_runs(report_id,schedule_id,runner,scheduled_at,origin) values(job.report_id,job.id,job.runner,job.next_at,'time') on conflict do nothing;
  update public.report_schedules set next_at=public.report_next_refresh(job.frequency,job.start_date,job.start_time,job.weekday,stamp,job.interval_minutes) where id=job.id;
 end loop;
 for ev in select * from public.report_refresh_events where not processed order by id for update skip locked limit 200 loop
  insert into public.report_refresh_runs(report_id,schedule_id,runner,scheduled_at,origin)
  select s.report_id,s.id,c.runner,ev.created_at,ev.event from public.report_schedules s join public.report_refresh_control c using(report_id)
  where s.kind='trigger' and s.trigger_event=ev.event and s.enabled and c.enabled and c.trigger_enabled
   and not exists(select 1 from public.report_refresh_runs r where r.report_id=s.report_id and (r.status in ('queued','in_progress') or r.scheduled_at>stamp-interval '2 minutes')) on conflict do nothing;
  update public.report_refresh_events set processed=true where id=ev.id;
 end loop;
 delete from public.report_refresh_events where processed and created_at<stamp-interval '1 day';
 return query update public.report_refresh_runs set schedule_group='claim-'||gen_random_uuid()::text where status='queued' and schedule_group is null returning *;
end;$$;
revoke all on function public.claim_report_refreshes() from public,anon,authenticated;
grant execute on function public.claim_report_refreshes() to service_role;
create or replace function public.prune_report_refresh_runs() returns void language sql security invoker set search_path=public,pg_catalog as $$
 delete from public.report_refresh_runs where id in (select id from (select id,row_number() over(partition by report_id order by scheduled_at desc,id desc) n from public.report_refresh_runs where status in ('completed','failed')) x where n>2)
$$;
revoke all on function public.prune_report_refresh_runs() from public,anon,authenticated;
grant execute on function public.prune_report_refresh_runs() to service_role;
create or replace function report_private.queue_new_order_refresh() returns trigger language plpgsql security definer set search_path=pg_catalog as $$
begin insert into public.report_refresh_events(event) values('new_order');return new;end;$$;
revoke all on function report_private.queue_new_order_refresh() from public,anon,authenticated;
create trigger report_new_order_schedule after insert on public.order_attribution_queue for each row execute function report_private.queue_new_order_refresh();
create or replace function report_private.queue_source_sync_refresh() returns trigger language plpgsql security definer set search_path=pg_catalog as $$
begin insert into public.report_refresh_events(event) values('source_sync');return new;end;$$;
revoke all on function report_private.queue_source_sync_refresh() from public,anon,authenticated;
create trigger report_source_sync_schedule after insert or update on sync.files for each statement execute function report_private.queue_source_sync_refresh();
