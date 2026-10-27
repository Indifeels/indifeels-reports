-- Stock log: every stock add / remove pushed to Shopify (Add / remove tab and box uploads).
-- The earlier migration 20261025120000 was never applied on the live database, so nothing was being logged. Safe to run either way.
create table if not exists public.stock_adjustments (
  id uuid primary key default gen_random_uuid(),
  vid text not null,
  product text not null default '',
  variant text not null default '',
  loc text not null default '',
  loc_name text not null default '',
  mode text not null check (mode in ('add','remove')),
  qty integer not null check (qty > 0),
  before_qty integer not null default 0,
  after_qty integer not null default 0,
  by_name text not null default '',
  created_at timestamptz not null default now()
);
alter table public.stock_adjustments add column if not exists box_no text not null default '';
create index if not exists stock_adjustments_vid on public.stock_adjustments (vid, created_at desc);
create index if not exists stock_adjustments_at on public.stock_adjustments (created_at desc);
alter table public.stock_adjustments enable row level security;
drop policy if exists stock_adjustments_read on public.stock_adjustments;
create policy stock_adjustments_read on public.stock_adjustments for select to authenticated
  using ((select public.can_view('stock-take')));
