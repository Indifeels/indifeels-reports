-- Project Board: due time, staged task reminders (12h / 6h / 30m / overdue), per-task mute.
alter table public.board_tasks
  add column due_time time,
  add column due_at timestamptz,
  add column mute_reminders boolean not null default false;

-- due_at = Melbourne wall-clock due date + time, as a real instant. Null unless both are set.
create function public.board_tasks_due_at() returns trigger language plpgsql set search_path='' as $$
begin
  if new.due_date is null then new.due_time := null; end if;
  new.due_at := case when new.due_date is not null and new.due_time is not null
    then (new.due_date + new.due_time) at time zone 'Australia/Melbourne' end;
  return new;
end;
$$;
create trigger board_tasks_due_at before insert or update on public.board_tasks
  for each row execute function public.board_tasks_due_at();
create index board_tasks_due_at_idx on public.board_tasks(due_at) where due_at is not null and col <> 'done';

-- One row per reminder already sent, so each stage fires once per due time.
create table public.board_reminder_log(
  task_id uuid not null references public.board_tasks(id) on delete cascade,
  stage text not null check (stage in ('12h','6h','30m','overdue')),
  due_at timestamptz not null,
  sent_at timestamptz not null default now(),
  primary key (task_id, stage, due_at)
);
alter table public.board_reminder_log enable row level security;

-- Run every 5 minutes so the 30-minute reminder lands on time (function does nothing when there is nothing to send).
select cron.unschedule('board-notify-30m');
select cron.schedule('board-notify-5m', '*/5 * * * *', $$select public.run_board_notify();$$);
