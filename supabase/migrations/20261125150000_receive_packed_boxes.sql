-- Selecting a box in Barcodes means it has arrived. A packed (not shipped) box can now be counted, received, held or reported:
-- receiving flips its lines and the box to shipped. Additive: no rows are deleted or reset.
create or replace function public.restock_owner_box_receive(p_items jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; eff integer; bx text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select (e->>'id') as id, greatest(coalesce((e->>'qty')::int, 0), 0) as qty from jsonb_array_elements(p_items) e loop
    select coalesce(ship_qty, qty), box_no into eff, bx from public.restock_orders
     where id = r.id and (status in ('added','shipped','on_the_way') or (status = 'received' and recv_qty < coalesce(ship_qty, qty)));
    if eff is null or r.qty = 0 then continue; end if;
    update public.restock_orders set recv_qty = least(recv_qty + r.qty, eff), updated_at = now(),
      ship_qty = coalesce(ship_qty, qty),
      shipped_at = coalesce(shipped_at, now()), ship_date = coalesce(ship_date, current_date),
      status = case when recv_qty + r.qty >= eff then 'received' when status = 'added' then 'shipped' else status end,
      hold_tag = case when recv_qty + r.qty >= eff then null else hold_tag end,
      received_at = case when recv_qty + r.qty >= eff then coalesce(received_at, now()) else received_at end
    where id = r.id;
    update public.restock_boxes set status = 'shipped', shipped_at = coalesce(shipped_at, now()), ship_date = coalesce(ship_date, current_date) where box_no = bx and status <> 'shipped';
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'received', r.qty, box_no from public.restock_orders where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

create or replace function public.restock_owner_box_hold(p_boxes text[])
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; rem integer; tag text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select * from public.restock_orders where box_no = any(p_boxes) and status in ('added','shipped','on_the_way') loop
    rem := coalesce(r.ship_qty, r.qty) - r.recv_qty;
    if rem <= 0 then continue; end if;
    tag := case when r.recv_qty > 0 then 'Partial: ' || r.recv_qty || ' added to stock, ' || rem || ' on the way' else rem || ' on the way' end;
    update public.restock_orders set status = 'on_the_way', ship_qty = coalesce(ship_qty, qty), shipped_at = coalesce(shipped_at, now()), ship_date = coalesce(ship_date, current_date), hold_tag = tag, updated_at = now() where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'on_the_way', rem, r.box_no);
    n := n + 1;
  end loop;
  update public.restock_boxes set status = 'shipped', shipped_at = coalesce(shipped_at, now()), ship_date = coalesce(ship_date, current_date) where box_no = any(p_boxes) and status <> 'shipped';
  return n;
end $$;

create or replace function public.restock_owner_box_short(p_box text)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; rem integer; nid text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select * from public.restock_orders where box_no = p_box and status in ('added','shipped','on_the_way') loop
    rem := coalesce(r.ship_qty, r.qty) - r.recv_qty;
    if rem <= 0 then continue; end if;
    if r.recv_qty > 0 then
      nid := coalesce(r.vkey, r.id) || '#' || nextval('public.restock_batch_seq');
      insert into public.restock_orders(id, product_id, product_title, image, variant_title, supplier, qty, status, saved_at, saved_by, vkey, claimed, orig_supplier, product_url, set_n, short_box)
        values (nid, r.product_id, r.product_title, r.image, r.variant_title, r.supplier, rem, 'saved', now(), r.saved_by, r.vkey, r.claimed, r.orig_supplier, r.product_url, r.set_n, p_box);
      update public.restock_orders set ship_qty = r.recv_qty, qty = least(qty, r.recv_qty), status = 'received', hold_tag = null, received_at = now(), updated_at = now() where id = r.id;
    else
      update public.restock_orders set status = 'saved', ship_qty = null, box_no = null, shipped_at = null, ship_date = null, added_at = null, hold_tag = null, short_box = p_box, updated_at = now() where id = r.id;
    end if;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'short', rem, p_box);
    n := n + 1;
  end loop;
  return n;
end $$;
