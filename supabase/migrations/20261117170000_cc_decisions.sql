-- Decisions Inbox for the Command Centre: bots suggest, admins approve.
create table if not exists public.cc_decisions (
  id text primary key,
  bot text not null,
  area text,
  title text not null,
  why text,
  change_detail text,
  risk text not null default 'approval' check (risk in ('low','approval')),
  status text not null default 'pending' check (status in ('pending','approved','rejected','applied','failed')),
  payload jsonb,
  result_note text,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  applied_at timestamptz
);
alter table public.cc_decisions enable row level security;
drop policy if exists cc_decisions_admin on public.cc_decisions;
create policy cc_decisions_admin on public.cc_decisions for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
