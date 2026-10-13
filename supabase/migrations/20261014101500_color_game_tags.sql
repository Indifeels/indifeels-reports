-- Colour Tagging Game: tags chosen in the report, replayed on open and later synced to Shopify.
create table public.color_tags(
  product_id text primary key,
  product_title text,
  colors text[] not null,
  updated_by uuid default auth.uid(),
  updated_at timestamptz not null default now(),
  synced_at timestamptz
);
create table public.color_new_colors(
  handle text primary key,
  label text not null,
  hex text,
  created_by uuid default auth.uid(),
  created_at timestamptz not null default now(),
  synced_at timestamptz
);
alter table public.color_tags enable row level security;
alter table public.color_new_colors enable row level security;
grant select,insert,update on public.color_tags,public.color_new_colors to authenticated;
grant all on public.color_tags,public.color_new_colors to service_role;
create policy color_tags_read on public.color_tags for select to authenticated using ((select public.can_view('color-game')));
create policy color_tags_insert on public.color_tags for insert to authenticated with check ((select public.can_view('color-game')));
create policy color_tags_update on public.color_tags for update to authenticated using ((select public.can_view('color-game'))) with check ((select public.can_view('color-game')));
create policy color_new_read on public.color_new_colors for select to authenticated using ((select public.can_view('color-game')));
create policy color_new_insert on public.color_new_colors for insert to authenticated with check ((select public.can_view('color-game')));
