-- Stock Take and Transfer report (owner only) + saved stock counts.
insert into public.reports(id, title, description, sort, category_id, admin_only) values
  ('stock-take', 'Stock Take and Transfer', 'Move stock between locations, and count stock by collection', 29, 'stock', true)
  on conflict (id) do nothing;

insert into public.report_refresh_control(report_id, enabled, runner) values ('stock-take', true, 'stock-take.yml')
  on conflict (report_id) do nothing;

create table if not exists public.stock_takes (
  id text primary key,
  name text not null,
  loc text not null,
  loc_name text not null default '',
  status text not null default 'open' check (status in ('open','ended')),
  filters jsonb not null default '{}'::jsonb,
  vids jsonb not null default '[]'::jsonb,       -- [[variant id, expected at start], ...]
  counts jsonb not null default '{}'::jsonb,     -- {variant id: scanned}
  outside jsonb not null default '{}'::jsonb,    -- scanned but outside the filter
  summary jsonb,                                 -- set when ended: expected, counted, missing, extra
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  updated_at timestamptz not null default now(),
  updated_by uuid default auth.uid()
);
alter table public.stock_takes enable row level security;
create policy stock_takes_all on public.stock_takes for all to authenticated
  using ((select public.can_view('stock-take'))) with check ((select public.can_view('stock-take')));
