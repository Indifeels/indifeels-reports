create table if not exists public.size_feedback(
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  user_id uuid default auth.uid(),
  chest numeric, tummy numeric, tall boolean, shoulders text,
  rec_size integer, alt_size integer, alt_type text, tried_size integer,
  slider numeric, verdict text, note text
);
alter table public.size_feedback enable row level security;
create policy size_feedback_admin on public.size_feedback for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
grant select, insert, update, delete on public.size_feedback to authenticated;
grant all on public.size_feedback to service_role;
