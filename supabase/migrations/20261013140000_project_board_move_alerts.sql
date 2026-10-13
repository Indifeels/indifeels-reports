-- Project Board: push a phone notification whenever a card changes column.
create function public.board_notify_moved() returns trigger language plpgsql security definer
  set search_path = 'public','extensions','net' as $$
begin
  perform net.http_post(
    url := 'https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/board-notify?action=moved&task=' || new.id
           || '&from=' || old.col || '&to=' || new.col,
    headers := jsonb_build_object('Content-Type','application/json','x-schedule-token',(select secret from report_private.scheduler_secret where id)),
    body := '{}'::jsonb,
    timeout_milliseconds := 15000
  );
  return null;
end;
$$;
revoke all on function public.board_notify_moved() from public, anon, authenticated;
grant execute on function public.board_notify_moved() to service_role;

create trigger board_tasks_moved after update of col on public.board_tasks
  for each row when (old.col is distinct from new.col)
  execute function public.board_notify_moved();
