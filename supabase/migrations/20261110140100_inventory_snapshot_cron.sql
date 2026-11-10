create or replace function public.run_inventory_snapshot() returns bigint
language plpgsql security definer set search_path to 'public','extensions','net' as $$
declare req_id bigint;
begin
  select net.http_post(
    url := 'https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/inventory-snapshot',
    headers := jsonb_build_object('Content-Type','application/json','x-schedule-token',(select secret from report_private.scheduler_secret where id)),
    body := '{}'::jsonb,
    timeout_milliseconds := 120000
  ) into req_id;
  return req_id;
end;
$$;
-- 14:10 UTC = 01:10 AEDT / 00:10 AEST, always just after midnight Melbourne.
select cron.schedule('inventory-snapshot-daily', '10 14 * * *', $$select public.run_inventory_snapshot();$$);
