-- supplier says "Not my product": the product's waiting lines go back to the order list with no supplier, and the tag is cleared (Shopify too, on the next build) so the owner can re-tag it
alter table public.restock_events drop constraint if exists restock_events_action_check;
alter table public.restock_events add constraint restock_events_action_check check (action in ('ordered','unordered','boxed','unboxed','qty','shipped','received','notmine'));

create or replace function public.restock_supplier_not_mine(p_product text) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); me text := public.restock_actor(); n integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if p_product is null or p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  with u as (
    update public.restock_orders o set supplier = 'Unassigned', updated_at = now()
    where o.product_id = p_product and o.status = 'saved' and not o.claimed and o.supplier = idn
    returning o.id, o.product_title, o.variant_title, o.qty),
  e as (
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
    select id, product_title || ' · ' || variant_title, idn, me, 'supplier', 'notmine', qty, qty from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'This product is not on your order list'; end if;
  insert into public.restock_product_tags(product_id, supplier, tagged_at, synced_at, override) values (p_product, '', now(), null, true)
    on conflict (product_id) do update set supplier = '', tagged_at = now(), synced_at = null, override = true;
  return n;
end $$;
revoke all on function public.restock_supplier_not_mine(text) from public, anon;
grant execute on function public.restock_supplier_not_mine(text) to authenticated, service_role;
