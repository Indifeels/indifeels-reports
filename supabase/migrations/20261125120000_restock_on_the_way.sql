-- "On the way": the owner holds the not-yet-received pieces of a box or PDF order (no supplier alert, not on the order sheet).
-- The line keeps its box / PDF code. Its tag says how much was added and how much is still on the way.
-- Receiving the rest later uses the same box receive; only the pending quantity shows (recv_qty is already counted).

alter table public.restock_orders add column if not exists hold_tag text check (hold_tag is null or length(hold_tag) <= 160);

alter table public.restock_orders drop constraint if exists restock_orders_status_check;
alter table public.restock_orders add constraint restock_orders_status_check
  check (status = any (array['saved'::text, 'added'::text, 'shipped'::text, 'received'::text, 'on_the_way'::text]));

alter table public.restock_events drop constraint if exists restock_events_action_check;
alter table public.restock_events add constraint restock_events_action_check
  check (action = any (array['ordered'::text, 'unordered'::text, 'boxed'::text, 'unboxed'::text, 'qty'::text, 'shipped'::text, 'received'::text, 'notmine'::text, 'short'::text, 'accepted'::text, 'on_the_way'::text]));

-- Box list: shipped and on-the-way lines, plus partly received lines still waiting for the rest
create or replace function public.restock_owner_box_list()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.shipped_at desc nulls first, x.box_no, x.product_title, x.variant_title) from (
    select o.id, o.box_no, o.product_id, o.product_title, o.image, o.variant_title, o.supplier,
           coalesce(o.ship_qty, o.qty) as qty, o.recv_qty, o.status as line_status, o.hold_tag,
           coalesce(b.status, 'open') as box_status, b.shipped_at, b.ship_date, b.tracking_no
    from public.restock_orders o
    left join public.restock_boxes b on b.box_no = o.box_no
    where o.box_no is not null and (o.status in ('added','shipped','on_the_way') or (o.status = 'received' and o.recv_qty < coalesce(o.ship_qty, o.qty)))
  ) x), '[]'::jsonb);
end $$;

-- Receive: shipped or on-the-way lines; a line that completes clears its hold tag
create or replace function public.restock_owner_box_receive(p_items jsonb)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; eff integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select (e->>'id') as id, greatest(coalesce((e->>'qty')::int, 0), 0) as qty from jsonb_array_elements(p_items) e loop
    select coalesce(ship_qty, qty) into eff from public.restock_orders where id = r.id and (status in ('shipped','on_the_way') or (status = 'received' and recv_qty < coalesce(ship_qty, qty)));
    if eff is null or r.qty = 0 then continue; end if;
    update public.restock_orders set recv_qty = least(recv_qty + r.qty, eff), updated_at = now(),
      status = case when recv_qty + r.qty >= eff then 'received' else status end,
      hold_tag = case when recv_qty + r.qty >= eff then null else hold_tag end,
      received_at = case when recv_qty + r.qty >= eff then coalesce(received_at, now()) else received_at end
    where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'received', r.qty, box_no from public.restock_orders where id = r.id;
    n := n + 1;
  end loop;
  return n;
end $$;

-- Hold due to receive: no supplier alert, nothing on the order sheet. Keeps the box / PDF code.
create or replace function public.restock_owner_box_hold(p_boxes text[])
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; rem integer; tag text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select * from public.restock_orders where box_no = any(p_boxes) and status in ('shipped','on_the_way') loop
    rem := coalesce(r.ship_qty, r.qty) - r.recv_qty;
    if rem <= 0 then continue; end if;
    tag := case when r.recv_qty > 0 then 'Partial: ' || r.recv_qty || ' added to stock, ' || rem || ' on the way'
                else rem || ' on the way' end;
    update public.restock_orders set status = 'on_the_way', hold_tag = tag, updated_at = now() where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'on_the_way', rem, r.box_no);
    n := n + 1;
  end loop;
  return n;
end $$;

-- Underreported (later): now also works for lines that are on the way
create or replace function public.restock_owner_box_short(p_box text)
returns integer language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); r record; n integer := 0; rem integer; nid text;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  for r in select * from public.restock_orders where box_no = p_box and status in ('shipped','on_the_way') loop
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

revoke all on function public.restock_owner_box_hold(text[]) from public, anon;
grant execute on function public.restock_owner_box_hold(text[]) to authenticated;
