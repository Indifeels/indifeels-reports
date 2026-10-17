-- Owner top-ups: if the same variant already sits unclaimed on the master list, a new order adds to that line
-- (2 on the list + 1 more = 3) instead of creating a duplicate line. Lines already in a supplier box or shipped
-- are left alone, so a new line is still created for them.
create or replace function public.restock_owner_order(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; vk text := p->>'vkey'; q integer := coalesce((p->>'qty')::integer, 0); me text := public.restock_actor(); sup text := left(coalesce(p->>'supplier',''), 100); old_q integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if vk is null or length(vk) > 100 then raise exception 'Bad id'; end if;
  if q <= 0 or q > 100000 then raise exception 'Quantity must be at least 1'; end if;
  if public.restock_blank_tag(sup) then
    select t.supplier into sup from public.restock_product_tags t where t.product_id = left(coalesce(p->>'product_id',''), 30);
    sup := coalesce(sup, left(coalesce(p->>'supplier',''), 100));
  end if;
  select * into r from public.restock_orders where vkey = vk and status = 'saved' and not claimed order by saved_at limit 1 for update;
  if found then
    old_q := r.qty;
    update public.restock_orders set qty = least(100000, qty + q), stock_base = coalesce(nullif(p->>'stock_base','')::integer, stock_base), updated_at = now()
      where id = r.id returning * into r;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', old_q, r.qty);
    return r;
  end if;
  insert into public.restock_orders(id, vkey, product_id, product_title, image, variant_title, supplier, qty, stock_base, saved_by, product_url)
  values (vk || '#' || nextval('public.restock_batch_seq'), vk, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          sup, q, nullif(p->>'stock_base','')::integer, auth.uid(),
          case when length(p->>'product_url') <= 500 and p->>'product_url' ~* '^https://[^ ]+$' then p->>'product_url' end)
  returning * into r;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', r.qty);
  return r;
end $$;
