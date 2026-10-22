-- discontinuing a product (owner button) now also removes its unshipped order lines, same as confirming a supplier's discontinue request
create or replace function public.restock_owner_set_discontinued(p_product text, p_value boolean) returns void
language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  insert into public.restock_discontinued(product_id, discontinued, requested_by_name) values (p_product, p_value, me)
  on conflict (product_id) do update set discontinued = excluded.discontinued, requested_by = auth.uid(), requested_by_name = excluded.requested_by_name;
  if p_value and p_product ~ '^[0-9]{1,20}$' then
    with d as (delete from public.restock_orders where product_id = p_product and status in ('saved','added') returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unordered', qty, 0, box_no from d;
  end if;
end $$;

-- clear the lines already left behind on discontinued products
with d as (delete from public.restock_orders o using public.restock_discontinued x
           where x.product_id = o.product_id and x.discontinued and o.status in ('saved','added') returning o.*)
insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to, box_no)
  select id, product_title || ' · ' || variant_title, supplier, 'system', 'owner', 'unordered', qty, 0, box_no from d;
