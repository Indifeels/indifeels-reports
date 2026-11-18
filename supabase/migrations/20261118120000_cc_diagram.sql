-- Editable connections diagram for the Command Centre (one row, id = 'main').
create table if not exists public.cc_diagram (
  id text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.cc_diagram enable row level security;
drop policy if exists cc_diagram_admin on public.cc_diagram;
create policy cc_diagram_admin on public.cc_diagram for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
