-- Barcode labels waiting for the next print run of the Indifeels label template.
-- Only the stock-adjust edge function (service role) reads or writes this table.
create table if not exists public.label_queue (
  id uuid primary key default gen_random_uuid(),
  vid text not null,
  product text not null default '',
  variant text not null default '',
  barcode text not null,
  copies integer not null default 1 check (copies between 1 and 5000),
  created_at timestamptz not null default now(),
  printed_at timestamptz
);
create index if not exists label_queue_open on public.label_queue (created_at) where printed_at is null;
alter table public.label_queue enable row level security;
