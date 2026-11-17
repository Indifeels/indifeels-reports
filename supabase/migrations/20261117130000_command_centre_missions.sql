-- Command Centre missions: answers and completed missions, admin only. Read by Claude to build the knowledge base.
create table if not exists public.cc_answers(
  qid text primary key check (qid ~ '^m-[a-z-]{1,30}\.[a-z]{1,20}$'),
  answer text not null default '' check (length(answer) <= 2000),
  parked boolean not null default false,
  updated_at timestamptz not null default now()
);
create table if not exists public.cc_missions_done(
  mid text primary key check (mid ~ '^m-[a-z-]{1,30}$'),
  done_at timestamptz not null default now()
);
alter table public.cc_answers enable row level security;
alter table public.cc_missions_done enable row level security;
create policy cc_answers_admin on public.cc_answers for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));
create policy cc_missions_done_admin on public.cc_missions_done for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));
grant select, insert, update, delete on public.cc_answers, public.cc_missions_done to authenticated;
grant all on public.cc_answers, public.cc_missions_done to service_role;
