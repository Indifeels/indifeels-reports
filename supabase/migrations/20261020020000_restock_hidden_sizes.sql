-- Sizes the owner no longer stocks. Hold a size name in the Restock Planner -> "Remove from dashboard" (hidden in the app only)
-- or "Remove from dashboard and Shopify" (the next planner build deletes that variant in Shopify, only if its stock is 0).
-- Bring a hidden size back with "Add size" (the planner un-hides it). Same pattern as restock_parked / restock_discontinued.
create table if not exists public.restock_hidden_sizes(
  vkey text primary key, product_id text not null, variant_title text not null,
  shopify_delete boolean not null default false, sync_error text,
  hidden_by uuid, hidden_at timestamptz not null default now());
alter table public.restock_hidden_sizes enable row level security;
revoke all on public.restock_hidden_sizes from anon, authenticated;
grant select on public.restock_hidden_sizes to authenticated;
drop policy if exists restock_hidden_sizes_read on public.restock_hidden_sizes;
create policy restock_hidden_sizes_read on public.restock_hidden_sizes for select to authenticated using ((select public.can_view('restock-plan')));

create or replace function public.restock_owner_set_size_hidden(p_vkey text, p_product text, p_title text, p_hidden boolean, p_shopify boolean default false) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if p_vkey is null or length(p_vkey) > 100 or p_vkey <> p_product || '|' || p_title then raise exception 'Bad size'; end if;
  if p_hidden then
    insert into public.restock_hidden_sizes(vkey, product_id, variant_title, shopify_delete, hidden_by) values (p_vkey, p_product, left(p_title, 120), coalesce(p_shopify, false), auth.uid())
    on conflict (vkey) do update set shopify_delete = public.restock_hidden_sizes.shopify_delete or excluded.shopify_delete, sync_error = null;
  else
    delete from public.restock_hidden_sizes where vkey = p_vkey;
  end if;
end $$;
revoke all on function public.restock_owner_set_size_hidden(text, text, text, boolean, boolean) from public, anon;
grant execute on function public.restock_owner_set_size_hidden(text, text, text, boolean, boolean) to authenticated;

-- called by the GitHub build (read token): sizes to delete in Shopify, then the result of each
create or replace function public.sync_get_restock_size_deletes(p_token text) returns table(vkey text, product_id text, variant_title text)
language plpgsql security definer set search_path = '' as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select h.vkey, h.product_id, h.variant_title from public.restock_hidden_sizes h where h.shopify_delete;
end $$;
create or replace function public.sync_mark_restock_size_deletes(p_token text, p_rows jsonb) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer := 0; x jsonb;
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  for x in select * from jsonb_array_elements(p_rows) loop
    if (x->>'ok')::boolean then
      delete from public.restock_hidden_sizes where vkey = x->>'vkey';           -- the variant is gone from Shopify: nothing left to hide
    else
      update public.restock_hidden_sizes set shopify_delete = false, sync_error = left(x->>'error', 300) where vkey = x->>'vkey';   -- stays hidden in the app only
    end if;
    n := n + 1;
  end loop;
  return n;
end $$;
revoke all on function public.sync_get_restock_size_deletes(text), public.sync_mark_restock_size_deletes(text, jsonb) from public, anon, authenticated;
grant execute on function public.sync_get_restock_size_deletes(text), public.sync_mark_restock_size_deletes(text, jsonb) to anon, authenticated, service_role;
