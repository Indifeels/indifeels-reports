-- Daily stock snapshot: one row per variant per Melbourne day (true in-stock days for days-to-sell).
create table if not exists public.inventory_snapshots(
  snap_date date not null,
  product_id bigint not null,
  variant_id bigint not null,
  qty integer not null,
  primary key (snap_date, variant_id)
);
create index if not exists inventory_snapshots_product_idx on public.inventory_snapshots(product_id, snap_date);
alter table public.inventory_snapshots enable row level security;

-- Festival / normal / off-peak windows (detected from Shopify weekly sales spikes, Nov 2026).
create table if not exists public.season_calendar(
  id bigint generated always as identity primary key,
  name text not null,
  start_date date not null,
  end_date date not null,
  season_type text not null check (season_type in ('festival','normal','offpeak')),
  note text,
  created_at timestamptz not null default now(),
  check (end_date >= start_date)
);
alter table public.season_calendar enable row level security;

insert into public.season_calendar(name, start_date, end_date, season_type, note) values
 ('Holi / Ugadi / Eid 2025',          '2025-03-10','2025-04-07','festival','peak 245 units/wk'),
 ('Raksha Bandhan / Ganesh 2025',     '2025-08-11','2025-09-15','festival','mild lift, ~1.7x'),
 ('Navratri to Diwali 2025',          '2025-09-22','2025-11-10','festival','peak 535 units/wk'),
 ('Holi / Ugadi / Eid 2026',          '2026-03-02','2026-03-22','festival','peak 235 units/wk'),
 ('Navratri to Diwali 2026',          '2026-10-05','2026-11-15','festival','Diwali 8 Nov 2026; end date provisional');
