-- owner can change a product's supplier; override=true lets the planner build push it to Shopify even if Shopify has an older value
alter table public.restock_product_tags add column if not exists override boolean not null default false;

create or replace function public.restock_owner_set_tag(p_product text, p_supplier text) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text := btrim(coalesce(p_supplier, '')); n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if public.restock_blank_tag(s) or length(s) > 100 then raise exception 'Pick a supplier'; end if;
  insert into public.restock_product_tags(product_id, supplier, tagged_at, synced_at, override) values (p_product, s, now(), null, true)
    on conflict (product_id) do update set supplier = excluded.supplier, tagged_at = now(), synced_at = null, override = true;
  update public.restock_orders set supplier = s, updated_at = now()
    where product_id = p_product and status = 'saved' and not claimed and supplier is distinct from s;
  get diagnostics n = row_count;
  return n;
end $$;

drop function if exists public.sync_get_restock_product_tags(text);
create function public.sync_get_restock_product_tags(p_token text) returns table(product_id text, supplier text, synced boolean, override boolean)
language plpgsql security definer set search_path = '' as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select t.product_id, t.supplier, t.synced_at is not null, t.override from public.restock_product_tags t;
end $$;
revoke all on function public.sync_get_restock_product_tags(text) from public, anon, authenticated;
grant execute on function public.sync_get_restock_product_tags(text) to anon, authenticated, service_role;
