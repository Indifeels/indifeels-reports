grant insert on public.report_refresh_runs to authenticated;
create policy runs_manual_admin on public.report_refresh_runs for insert to authenticated with check(public.is_admin() and origin='manual' and status='queued' and schedule_id is null and schedule_group is null and exists(select 1 from public.report_refresh_control c where c.report_id=report_refresh_runs.report_id and c.runner=report_refresh_runs.runner));
create or replace function public.request_report_refresh(p_report text) returns jsonb language plpgsql security invoker set search_path=public,pg_catalog as $$
declare c public.report_refresh_control; existing uuid; new_id uuid;
begin
 if not public.is_admin() then raise exception 'Only admins can refresh reports';end if;
 perform pg_advisory_xact_lock(hashtextextended('manual-refresh:'||p_report,0));
 select * into c from public.report_refresh_control where report_id=p_report;
 if c.runner is null then raise exception 'No data refresh runner is connected for this report';end if;
 select id into existing from public.report_refresh_runs where report_id=p_report and status in ('queued','in_progress') order by scheduled_at desc limit 1;
 if existing is not null then return jsonb_build_object('id',existing,'already_running',true);end if;
 if exists(select 1 from public.report_refresh_runs where report_id=p_report and origin='manual' and scheduled_at>now()-interval '1 minute') then raise exception 'Please wait one minute before requesting another refresh';end if;
 insert into public.report_refresh_runs(report_id,runner,scheduled_at,origin,detail) values(p_report,c.runner,now(),'manual','Manual refresh requested; waiting for runner') returning id into new_id;
 return jsonb_build_object('id',new_id,'already_running',false);
end;$$;
revoke all on function public.request_report_refresh(text) from public,anon;
grant execute on function public.request_report_refresh(text) to authenticated;