-- Supplier packs less than ordered: the box keeps only what was packed, the shortfall goes back to the master list
-- (merged into an unclaimed line of the same variant when one exists, so owner top-ups and shortfalls stay on one line).
create or replace function public.restock_supplier_set_qty(p_id text, p_qty integer) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); me text := public.restock_actor(); r public.restock_orders; m public.restock_orders; rest integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if p_qty is null then return 0; end if;
  select * into r from public.restock_orders where id = p_id and claimed and supplier = idn and status = 'added' for update;
  if not found then return 0; end if;

  if p_qty >= r.qty then                               -- back to the full amount (also clears an old-style "short" flag)
    update public.restock_orders set ship_qty = null, qty_by_name = null, updated_at = now() where id = r.id;
    if r.ship_qty is not null then
      insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
        values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'supplier', 'qty', r.ship_qty, r.qty);
    end if;
    return 1;
  end if;

  if p_qty <= 0 then                                    -- nothing packed: the whole line goes back to the master list
    update public.restock_orders set status = 'saved', claimed = false, supplier = coalesce(r.orig_supplier, r.supplier), box_no = null,
        added_at = null, ship_qty = null, qty_by_name = null, updated_at = now() where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'supplier', 'unboxed', r.qty);
    return 1;
  end if;

  rest := r.qty - p_qty;                                -- split: p_qty stays in the box, rest returns to the master list
  update public.restock_orders set qty = p_qty, ship_qty = null, qty_by_name = me, updated_at = now() where id = r.id;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'supplier', 'qty', r.qty, p_qty);
  if r.vkey is not null then
    select * into m from public.restock_orders where vkey = r.vkey and status = 'saved' and not claimed and id <> r.id order by saved_at limit 1 for update;
  end if;
  if found and m.id is not null then
    update public.restock_orders set qty = least(100000, qty + rest), updated_at = now() where id = m.id;
  else
    insert into public.restock_orders(id, vkey, product_id, product_title, product_url, image, variant_title, supplier, qty, stock_base, saved_by, saved_at)
    values (coalesce(r.vkey, r.id) || '#' || nextval('public.restock_batch_seq'), coalesce(r.vkey, r.id), r.product_id, r.product_title, r.product_url, r.image,
            r.variant_title, coalesce(r.orig_supplier, r.supplier), rest, r.stock_base, r.saved_by, r.saved_at);
  end if;
  return 1;
end $$;
revoke all on function public.restock_supplier_set_qty(text, integer) from public, anon;
grant execute on function public.restock_supplier_set_qty(text, integer) to authenticated, service_role;
