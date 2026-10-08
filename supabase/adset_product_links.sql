-- Ad set -> product links for the Daily (non-tracked) report's stock bar.
-- The user pastes a product page link into an ad set's box; the product handle is stored here and the
-- nightly build (and the report page, straight after saving) shows that product's variant stock.

create table if not exists public.adset_product_links (
  adset_id   text primary key,                       -- Meta ad set id
  handle     text not null,                          -- Shopify product handle parsed from the pasted link
  title      text,                                   -- product title at the time of linking (display only)
  linked_by  uuid,
  updated_at timestamptz not null default now()
);
alter table public.adset_product_links enable row level security;   -- no policies: only the function below and the build RPC touch it

-- Called by the GitHub build with the existing read token.
create or replace function public.sync_get_adset_product_links(p_token text)
returns table(adset_id text, handle text)
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select l.adset_id, l.handle from public.adset_product_links l;
end $$;
grant execute on function public.sync_get_adset_product_links(text) to anon, authenticated, service_role;
