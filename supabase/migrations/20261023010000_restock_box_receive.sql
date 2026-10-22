alter table public.restock_orders
  add column if not exists recv_qty integer not null default 0 check (recv_qty >= 0),
  add column if not exists short_box text;

alter table public.restock_events drop constraint if exists restock_events_action_check;
alter table public.restock_events add constraint restock_events_action_check
  check (action = any (array['ordered','unordered','boxed','unboxed','qty','shipped','received','notmine','short']));

-- Owner: lines in packed (open) or shipped boxes, with box status
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
    where o.box_no is not null and o.status in ('added','shipped')
  ) x), '[]'::jsonb);
end $$;

-- Owner: record stock actually added; p_items = [{"id":..,"qty":n}]
create or replace function public.restock_owner_box_receive(p_items jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; eff integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select (e->>'id') as id, greatest(coalesce((e->>'qty')::int, 0), 0) as qty from jsonb_array_elements(p_items) e loop
    select coalesce(ship_qty, qty) into eff from public.restock_orders where id = r.id and status = 'shipped';
    if eff is null or r.qty = 0 then continue; end if;
    update public.restock_orders set recv_qty = least(recv_qty + r.qty, eff), updated_at = now(),
      status = case when recv_qty + r.qty >= eff then 'received' else status end,
      received_at = case when recv_qty + r.qty >= eff then now() else received_at end
    where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'received', r.qty, box_no from public.restock_orders where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

-- Owner: whatever is still not received in a box goes back to the supplier as "not received"
create or replace function public.restock_owner_box_short(p_box text)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; rem integer; nid text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select * from public.restock_orders where box_no = p_box and status = 'shipped' loop
    rem := coalesce(r.ship_qty, r.qty) - r.recv_qty;
    if rem <= 0 then continue; end if;
    if r.recv_qty > 0 then
      nid := coalesce(r.vkey, r.id) || '#' || nextval('public.restock_batch_seq');
      insert into public.restock_orders(id, product_id, product_title, image, variant_title, supplier, qty, status, saved_at, saved_by, vkey, claimed, orig_supplier, product_url, set_n, short_box)
        values (nid, r.product_id, r.product_title, r.image, r.variant_title, r.supplier, rem, 'saved', now(), r.saved_by, r.vkey, r.claimed, r.orig_supplier, r.product_url, r.set_n, p_box);
      update public.restock_orders set ship_qty = r.recv_qty, qty = least(qty, r.recv_qty), status = 'received', received_at = now(), updated_at = now() where id = r.id;
    else
      update public.restock_orders set status = 'saved', ship_qty = null, box_no = null, shipped_at = null, ship_date = null, added_at = null, short_box = p_box, updated_at = now() where id = r.id;
    end if;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'short', rem, p_box);
    n := n + 1;
  end loop;
  return n;
end $$;

revoke all on function public.restock_owner_box_list() from public, anon;
revoke all on function public.restock_owner_box_receive(jsonb) from public, anon;
revoke all on function public.restock_owner_box_short(text) from public, anon;
grant execute on function public.restock_owner_box_list() to authenticated;
grant execute on function public.restock_owner_box_receive(jsonb) to authenticated;
grant execute on function public.restock_owner_box_short(text) to authenticated;

-- Supplier state now also exposes short_box (items the owner reported as not received) and recv_qty
create or replace function public.restock_supplier_state()
 returns jsonb language plpgsql security definer set search_path to ''
as $function$
declare idn text := public.restock_box_identity(); c text; act text; mx integer; orders jsonb; boxes jsonb; mycol text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  select u.collection into mycol from public.restock_supplier_users u where u.user_id = auth.uid();
  select box_no into act from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if act is null then
    select coalesce(max(seq), 0) + 1 into mx from public.restock_boxes where code = c;
    act := 'Box-' || c || '-' || lpad(mx::text, 2, '0');
  end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.product_id, x.variant_title, x.saved_at), '[]'::jsonb) into orders from (
    select o.id, o.vkey, o.product_id, o.product_title, o.product_url, o.image, o.variant_title, o.qty, o.set_n, o.ship_qty, o.recv_qty, o.short_box, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.claimed,
           (not o.claimed and public.restock_tag_mismatch(o.supplier, idn)) as tagged_other,
           (not o.claimed and btrim(coalesce(o.supplier, '')) not in ('', 'Unassigned') and not public.restock_tag_mismatch(o.supplier, idn)) as tagged_mine
    from public.restock_orders o
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')
      and (mycol is null or o.claimed or exists (select 1 from public.restock_product_cols pc where pc.product_id = o.product_id and mycol = any(pc.cols)))) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $function$;
