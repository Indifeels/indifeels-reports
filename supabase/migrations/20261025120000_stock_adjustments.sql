-- Every Add / remove stock change made in the Stock Take app (outside a stock take), so a variant's history can show it separately.
-- Written only by the stock-adjust edge function (service role); the owner reads it through the Stock Take report permission.
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
create index if not exists stock_adjustments_vid on public.stock_adjustments (vid, created_at desc);
alter table public.stock_adjustments enable row level security;
create policy stock_adjustments_read on public.stock_adjustments for select to authenticated
  using ((select public.can_view('stock-take')));
