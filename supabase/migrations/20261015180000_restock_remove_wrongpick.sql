-- Remove lines / delete boxes, and "wrong pick" detection (a supplier picks an item tagged to a different supplier).
-- Run AFTER 20261015170000_restock_boxes_master_list.sql.

alter table public.restock_orders add column wrong_pick boolean not null default false, add column wrong_ack boolean not null default false;

-- does the product's supplier tag point at somebody other than this login? (Unassigned / blank = nobody)
create function public.restock_tag_mismatch(tag text, idn text) returns boolean
language sql immutable set search_path = '' as $$
  select btrim(coalesce(tag, '')) not in ('', 'Unassigned')
     and position(lower(btrim(tag)) in lower(coalesce(idn, ''))) = 0
     and position(lower(coalesce(idn, '')) in lower(btrim(tag))) = 0
$$;

-- supplier page data: same as before plus tagged_other (without revealing whose tag it is)
create or replace function public.restock_supplier_state() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; act text; mx integer; orders jsonb; boxes jsonb;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  select box_no into act from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if act is null then
    select coalesce(max(seq), 0) + 1 into mx from public.restock_boxes where code = c;
    act := 'Box-' || c || '-' || lpad(mx::text, 2, '0');
  end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.product_id, x.variant_title, x.saved_at), '[]'::jsonb) into orders from (
    select o.id, o.vkey, o.product_id, o.image, o.variant_title, o.qty, o.ship_qty, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.claimed,
           (not o.claimed and public.restock_tag_mismatch(o.supplier, idn)) as tagged_other
    from public.restock_orders o
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $$;

-- pick lines into a box. Lines tagged to another supplier need p_confirm = true; those are flagged for the owner.
create function public.restock_supplier_pick(p_ids text[], p_box text default null, p_confirm boolean default false) returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; target text; sq integer; n integer; me text := public.restock_actor(); wp text[];
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  c := public.restock_my_code();
  select array_agg(o.id) into wp from public.restock_orders o
    where o.id = any(p_ids) and o.status = 'saved' and not o.claimed and public.restock_tag_mismatch(o.supplier, idn);
  if wp is not null and not coalesce(p_confirm, false) then raise exception 'TAGGED_OTHER: % item(s) are tagged to another supplier', array_length(wp, 1); end if;
  if p_box is null then
    select box_no into target from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
    if target is null then
      select coalesce(max(seq), 0) + 1 into sq from public.restock_boxes where code = c;
      target := 'Box-' || c || '-' || lpad(sq::text, 2, '0');
      insert into public.restock_boxes(box_no, code, seq, supplier) values (target, c, sq, idn);
    end if;
  else
    select box_no into target from public.restock_boxes where box_no = p_box and code = c and status = 'open';
    if target is null then raise exception 'That box is not available'; end if;
  end if;
  with u as (
    update public.restock_orders o set status = 'added', added_at = coalesce(o.added_at, now()), box_no = target, supplier = idn, claimed = true,
        orig_supplier = coalesce(o.orig_supplier, case when o.claimed then null else o.supplier end), added_by_name = me, updated_at = now()
    where o.id = any(p_ids) and (
        (o.status = 'saved' and not o.claimed)
        or (o.status = 'added' and (not o.claimed or o.supplier = idn)
            and (o.box_no is null or o.box_no in (select b.box_no from public.restock_boxes b where b.code = c and b.status = 'open'))))
    returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
        select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'boxed', coalesce(ship_qty, qty), target from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'Nothing to add: those items are no longer on the master list'; end if;
  if wp is not null then
    with w as (update public.restock_orders set wrong_pick = true, wrong_ack = false where id = any(wp) and claimed and supplier = idn returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, '⚠ WRONG PICK · ' || product_title || ' · ' || variant_title || ' (tagged to ' || coalesce(orig_supplier, '?') || ')', supplier, me, 'supplier', 'boxed', coalesce(ship_qty, qty), target from w;
  end if;
  return target;
end $$;

create or replace function public.restock_supplier_remove(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  c := public.restock_my_code();
  with u as (
    update public.restock_orders o set status = 'saved', claimed = false, supplier = coalesce(o.orig_supplier, o.supplier), box_no = null,
        added_at = null, ship_qty = null, qty_by_name = null, wrong_pick = false, wrong_ack = false, updated_at = now()
    where o.id = any(p_ids) and o.claimed and o.supplier = idn and o.status = 'added'
      and o.box_no in (select b.box_no from public.restock_boxes b where b.code = c and b.status = 'open')
    returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
        select id, product_title || ' · ' || variant_title, idn, me, 'supplier', 'unboxed', qty from u returning 1)
  select count(*) into n from u;
  return n;
end $$;

-- delete one of my open boxes: its lines go back to the master list
create function public.restock_supplier_delete_box(p_box text) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  if not exists (select 1 from public.restock_boxes where box_no = p_box and code = c and status = 'open') then raise exception 'That box cannot be deleted'; end if;
  with u as (
    update public.restock_orders o set status = 'saved', claimed = false, supplier = coalesce(o.orig_supplier, o.supplier), box_no = null,
        added_at = null, ship_qty = null, qty_by_name = null, wrong_pick = false, wrong_ack = false, updated_at = now()
    where o.box_no = p_box and o.status = 'added' and o.supplier = idn returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
        select id, product_title || ' · ' || variant_title, idn, me, 'supplier', 'unboxed', qty from u returning 1),
  g as (delete from public.restock_boxes where box_no = p_box and code = c and status = 'open' returning 1)
  select count(*) into n from u;
  return n;
end $$;

-- owner: remove a line that is not shipped yet (master list or in a supplier's box)
create or replace function public.restock_owner_cancel(p_id text) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  with d as (delete from public.restock_orders where id = p_id and status in ('saved','added') returning *)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to, box_no)
    select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unordered', qty, 0, box_no from d;
  get diagnostics n = row_count;
  return n;
end $$;

-- owner: send a wrongly picked line back to the master list
create function public.restock_owner_release(p_id text) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  with u as (
    update public.restock_orders o set status = 'saved', claimed = false, supplier = coalesce(o.orig_supplier, o.supplier), box_no = null,
        added_at = null, ship_qty = null, qty_by_name = null, wrong_pick = false, wrong_ack = false, updated_at = now()
    where o.id = p_id and o.status = 'added' returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
        select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unboxed', qty from u returning 1)
  select count(*) into n from u;
  return n;
end $$;

-- owner: "this pick is fine"
create function public.restock_owner_ack_wrong(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  update public.restock_orders set wrong_ack = true where id = any(p_ids) and wrong_pick;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.restock_tag_mismatch(text, text), public.restock_supplier_pick(text[], text, boolean), public.restock_supplier_delete_box(text),
  public.restock_owner_release(text), public.restock_owner_ack_wrong(text[]) from public, anon, authenticated;
grant execute on function public.restock_tag_mismatch(text, text), public.restock_supplier_pick(text[], text, boolean), public.restock_supplier_delete_box(text),
  public.restock_owner_release(text), public.restock_owner_ack_wrong(text[]) to authenticated, service_role;
revoke all on function public.restock_supplier_add(text[], text) from public, anon, authenticated;

-- delete a box: only the LATEST open box can go; its lines move to another open box (p_to) or back to the master list
create function public.restock_supplier_delete_box2(p_box text, p_to text default null) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer; me text := public.restock_actor(); lastno text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  if not exists (select 1 from public.restock_boxes where box_no = p_box and code = c and status = 'open') then raise exception 'That box cannot be deleted'; end if;
  select box_no into lastno from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if lastno <> p_box then raise exception 'Delete % first: boxes are removed from the newest one down', lastno; end if;
  if p_to is not null and p_to <> '' and not exists (select 1 from public.restock_boxes where box_no = p_to and code = c and status = 'open' and box_no <> p_box) then
    raise exception 'That destination box is not available';
  end if;
  if p_to is not null and p_to <> '' then
    with u as (update public.restock_orders o set box_no = p_to, updated_at = now()
               where o.box_no = p_box and o.status = 'added' and o.supplier = idn returning o.*),
    e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, box_no)
          select id, product_title || ' · ' || variant_title, idn, me, 'supplier', 'boxed', p_to from u returning 1),
    g as (delete from public.restock_boxes where box_no = p_box and code = c and status = 'open' returning 1)
    select count(*) into n from u;
  else
    with u as (update public.restock_orders o set status = 'saved', claimed = false, supplier = coalesce(o.orig_supplier, o.supplier), box_no = null,
          added_at = null, ship_qty = null, qty_by_name = null, wrong_pick = false, wrong_ack = false, updated_at = now()
        where o.box_no = p_box and o.status = 'added' and o.supplier = idn returning o.*),
    e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
          select id, product_title || ' · ' || variant_title, idn, me, 'supplier', 'unboxed', qty from u returning 1),
    g as (delete from public.restock_boxes where box_no = p_box and code = c and status = 'open' returning 1)
    select count(*) into n from u;
  end if;
  return n;
end $$;
revoke all on function public.restock_supplier_delete_box2(text, text) from public, anon, authenticated;
grant execute on function public.restock_supplier_delete_box2(text, text) to authenticated, service_role;
revoke all on function public.restock_supplier_delete_box(text) from public, anon, authenticated;
