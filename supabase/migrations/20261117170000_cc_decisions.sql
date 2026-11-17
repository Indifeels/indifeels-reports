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

-- Info cards ("for your info", Got it) and a log of bot runs
alter table public.cc_decisions drop constraint if exists cc_decisions_risk_check;
alter table public.cc_decisions add constraint cc_decisions_risk_check check (risk in ('low','approval','info'));
alter table public.cc_decisions drop constraint if exists cc_decisions_status_check;
alter table public.cc_decisions add constraint cc_decisions_status_check check (status in ('pending','approved','rejected','applied','failed','seen'));
create table if not exists public.cc_bot_runs (
  id bigserial primary key,
  bot text not null,
  ran_at timestamptz not null default now(),
  summary text
);
alter table public.cc_bot_runs enable row level security;
drop policy if exists cc_bot_runs_admin on public.cc_bot_runs;
create policy cc_bot_runs_admin on public.cc_bot_runs for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));

-- Cancel (before the bot applies) and Revert (after)
alter table public.cc_decisions drop constraint if exists cc_decisions_status_check;
alter table public.cc_decisions add constraint cc_decisions_status_check check (status in ('pending','approved','rejected','applied','failed','seen','cancelled','revert_requested','reverted'));
alter table public.cc_decisions add column if not exists reversible text not null default 'yes' check (reversible in ('yes','partly','no'));
alter table public.cc_decisions add column if not exists undo_detail text;
