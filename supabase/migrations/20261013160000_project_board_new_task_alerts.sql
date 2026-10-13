-- Project Board: push a phone notification when a new task is added (by anyone: board, Claude, ChatGPT).
create function public.board_notify_added() returns trigger language plpgsql security definer
  set search_path = 'public','extensions','net' as $$
begin
  perform net.http_post(
    url := 'https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/board-notify?action=moved&task=' || new.id || '&from=new&to=' || new.col,
    headers := jsonb_build_object('Content-Type','application/json','x-schedule-token',(select secret from report_private.scheduler_secret where id)),
    body := '{}'::jsonb,
    timeout_milliseconds := 15000
  );
  return null;
end;
$$;
revoke all on function public.board_notify_added() from public, anon, authenticated;
grant execute on function public.board_notify_added() to service_role;

create trigger board_tasks_added after insert on public.board_tasks
  for each row execute function public.board_notify_added();
