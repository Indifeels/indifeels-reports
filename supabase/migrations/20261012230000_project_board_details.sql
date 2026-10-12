-- Project Board v2: due dates, comments, attachments, overdue digest state.

-- Due date (date only, Melbourne calendar day).
alter table public.board_tasks add column due_date date;
create index board_tasks_due on public.board_tasks(due_date) where due_date is not null and col <> 'done';

-- Comments. author_id is null for comments written by Claude / ChatGPT through the service role.
create table public.board_comments(
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.board_tasks(id) on delete cascade,
  body text not null check (length(btrim(body)) between 1 and 2000),
  author_id uuid default auth.uid(),
  author_name text not null default 'Unknown' check (length(author_name) <= 80),
  created_at timestamptz not null default now()
);
create index board_comments_task on public.board_comments(task_id, created_at);

-- Attachments: metadata row per file; the file itself lives in the private 'board-attachments' bucket.
create table public.board_attachments(
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.board_tasks(id) on delete cascade,
  path text not null unique,
  name text not null check (length(name) between 1 and 200),
  size bigint check (size is null or size between 0 and 10485760),
  mime text,
  uploaded_by text not null default 'Unknown' check (length(uploaded_by) <= 80),
  created_at timestamptz not null default now()
);
create index board_attachments_task on public.board_attachments(task_id, created_at);

alter table public.board_comments enable row level security;
alter table public.board_attachments enable row level security;
create policy board_comments_admin_all on public.board_comments for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
create policy board_attachments_admin_all on public.board_attachments for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
grant select,insert,update,delete on public.board_comments, public.board_attachments to authenticated;
grant all on public.board_comments, public.board_attachments to service_role;

-- Private bucket, admins only, 10 MB per file, no HTML/SVG/script types.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values(
  'board-attachments','board-attachments',false,10485760,
  array['image/png','image/jpeg','image/webp','image/gif','image/heic','application/pdf','text/plain','text/csv',
        'application/msword','application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation']
) on conflict (id) do nothing;
create policy board_attachments_read on storage.objects for select to authenticated
  using (bucket_id='board-attachments' and (select public.is_admin()));
create policy board_attachments_insert on storage.objects for insert to authenticated
  with check (bucket_id='board-attachments' and (select public.is_admin()));
create policy board_attachments_delete on storage.objects for delete to authenticated
  using (bucket_id='board-attachments' and (select public.is_admin()));

-- Overdue digest: one push per Melbourne day, sent by the board-notify edge function.
create table public.board_notify_state(
  id integer primary key check (id = 1),
  last_digest_on date
);
alter table public.board_notify_state enable row level security;
insert into public.board_notify_state(id) values (1);

create function public.run_board_notify() returns bigint language plpgsql security definer
  set search_path = 'public','extensions','net' as $$
declare req_id bigint;
begin
  select net.http_post(
    url := 'https://yrigvovwyfpaybibfjva.supabase.co/functions/v1/board-notify?action=check',
    headers := jsonb_build_object('Content-Type','application/json','x-schedule-token',(select secret from report_private.scheduler_secret where id)),
    body := '{}'::jsonb,
    timeout_milliseconds := 20000
  ) into req_id;
  return req_id;
end;
$$;
revoke all on function public.run_board_notify() from public, anon, authenticated;
grant execute on function public.run_board_notify() to service_role;

-- Checks every 30 minutes (UTC cron); the function itself only sends between 8:30 am and 8:00 pm Melbourne time, once per day.
select cron.schedule('board-notify-30m', '*/30 * * * *', $$select public.run_board_notify();$$);
