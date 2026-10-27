-- Lines marked "received" by the old Received button (recv_qty still below the sent quantity) go back into the Barcodes box list,
-- so their barcodes can be printed and their stock added. Plus a read-only per-box view (box qty incl. over reported) for the printed-barcodes history.
create or replace function public.restock_owner_box_list()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.shipped_at desc nulls first, x.box_no, x.product_title, x.variant_title) from (
    select o.id, o.box_no, o.product_id, o.product_title, o.image, o.variant_title, o.supplier,
           coalesce(o.ship_qty, o.qty) as qty, o.recv_qty, o.status as line_status,
           coalesce(b.status, 'open') as box_status, b.shipped_at, b.ship_date, b.tracking_no
    from public.restock_orders o
    left join public.restock_boxes b on b.box_no = o.box_no
    where o.box_no is not null and (o.status in ('added','shipped') or (o.status = 'received' and o.recv_qty < coalesce(o.ship_qty, o.qty)))
  ) x), '[]'::jsonb);
end $$;

create or replace function public.restock_owner_box_receive(p_items jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; eff integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select (e->>'id') as id, greatest(coalesce((e->>'qty')::int, 0), 0) as qty from jsonb_array_elements(p_items) e loop
    select coalesce(ship_qty, qty) into eff from public.restock_orders where id = r.id and (status = 'shipped' or (status = 'received' and recv_qty < coalesce(ship_qty, qty)));
    if eff is null or r.qty = 0 then continue; end if;
    update public.restock_orders set recv_qty = least(recv_qty + r.qty, eff), updated_at = now(),
      status = case when recv_qty + r.qty >= eff then 'received' else status end,
      received_at = case when recv_qty + r.qty >= eff then coalesce(received_at, now()) else received_at end
    where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'received', r.qty, box_no from public.restock_orders where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

create or replace function public.restock_owner_box_print_view()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.box_no, x.product_title, x.variant_title) from (
    select coalesce(o.box_no, o.short_box) as box_no, o.product_id, o.product_title, o.image, o.variant_title,
           sum(case when o.box_no is not null then coalesce(o.ship_qty, o.qty) else 0 end)::int as box_qty,
           sum(case when o.box_no is null and o.short_box is not null then o.qty else 0 end)::int as over_qty
    from public.restock_orders o
    where (o.box_no is not null and o.status in ('added','shipped','received')) or (o.short_box is not null and o.status = 'saved')
    group by 1, o.product_id, o.product_title, o.image, o.variant_title
  ) x), '[]'::jsonb);
end $$;
revoke all on function public.restock_owner_box_print_view() from public, anon;
grant execute on function public.restock_owner_box_print_view() to authenticated;
