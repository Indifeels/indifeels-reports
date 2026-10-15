-- Master list + per-supplier boxes.
--  * Everything the owner saves is on a master list every supplier can see ("unclaimed").
--  * A supplier claims a line with "Add to box": the line moves into that supplier's own open box (Box-P1-01 ...),
--    and the line's supplier becomes that supplier. Other suppliers can no longer see it, their boxes or shipping.
--  * A supplier can start a new box, move lines between their open boxes, send a line back to the master list,
--    ship a whole box (date + optional tracking link/number) and edit tracking later.
-- Run AFTER 20261015160000_restock_batches_boxes_discontinued.sql.

alter table public.restock_orders add column claimed boolean not null default false, add column orig_supplier text;

alter table public.restock_boxes
  add column supplier text,
  add column status text not null default 'open' check (status in ('open','shipped')),
  add column shipped_at timestamptz,
  add column ship_date date,
  add column tracking_url text check (tracking_url is null or (tracking_url ~ '^https?://' and length(tracking_url) <= 500)),
  add column tracking_no text check (tracking_no is null or length(tracking_no) <= 80);
update public.restock_boxes b set status = 'shipped',
  supplier = (select o.supplier from public.restock_orders o where o.box_no = b.box_no limit 1),
  ship_date = (select max(o.ship_date) from public.restock_orders o where o.box_no = b.box_no),
  shipped_at = (select max(o.shipped_at) from public.restock_orders o where o.box_no = b.box_no);
grant select on public.restock_boxes to authenticated;
create policy restock_boxes_owner_read on public.restock_boxes for select to authenticated using ((select public.can_view('restock-plan')));

-- the login's supplier code (P1, V1 ...): first letter of the supplier name + a running number per letter
create function public.restock_my_code() returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; l text;
begin
  perform pg_advisory_xact_lock(hashtext('restock_box'));
  select code into c from public.restock_supplier_codes where identity = idn;
  if c is null then
    l := upper(coalesce(nullif(substr(regexp_replace(idn, '[^A-Za-z0-9]', '', 'g'), 1, 1), ''), 'X'));
    c := l || (1 + (select count(*) from public.restock_supplier_codes where code ~ ('^' || l || '[0-9]+$')));
    insert into public.restock_supplier_codes(identity, code) values (idn, c);
  end if;
  return c;
end $$;

-- everything the supplier page needs in one call
create function public.restock_supplier_state() returns jsonb
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
    select o.id, o.vkey, o.product_id, o.image, o.variant_title, o.qty, o.ship_qty, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.claimed
    from public.restock_orders o
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $$;

-- claim lines (from the master list) or move own lines between open boxes; p_box null = the current open box (created if none)
create function public.restock_supplier_add(p_ids text[], p_box text default null) returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; target text; sq integer; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  c := public.restock_my_code();
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
  return target;
end $$;

-- send own lines back to the master list
create function public.restock_supplier_remove(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  c := public.restock_my_code();
  with u as (
    update public.restock_orders o set status = 'saved', claimed = false, supplier = coalesce(o.orig_supplier, o.supplier), box_no = null,
        added_at = null, ship_qty = null, qty_by_name = null, updated_at = now()
    where o.id = any(p_ids) and o.claimed and o.supplier = idn and o.status = 'added'
      and o.box_no in (select b.box_no from public.restock_boxes b where b.code = c and b.status = 'open')
    returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
        select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'unboxed', qty from u returning 1)
  select count(*) into n from u;
  return n;
end $$;

-- start the next box (does nothing while the current one is still empty)
create function public.restock_supplier_new_box() returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; act text; sq integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  select box_no into act from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if act is not null and not exists (select 1 from public.restock_orders where box_no = act and status = 'added') then return act; end if;
  select coalesce(max(seq), 0) + 1 into sq from public.restock_boxes where code = c;
  act := 'Box-' || c || '-' || lpad(sq::text, 2, '0');
  insert into public.restock_boxes(box_no, code, seq, supplier) values (act, c, sq, idn);
  return act;
end $$;

create function public.restock_supplier_ship_box(p_box text, p_date date, p_url text default null, p_no text default null) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer; me text := public.restock_actor(); url text := nullif(btrim(coalesce(p_url, '')), ''); tno text := nullif(btrim(coalesce(p_no, '')), '');
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  if not exists (select 1 from public.restock_boxes where box_no = p_box and code = c and status = 'open') then raise exception 'That box is not open'; end if;
  if p_date is null or p_date > current_date + 1 or p_date < current_date - 30 then raise exception 'Ship date must be within the last 30 days'; end if;
  if url is not null and (url !~ '^https?://' or length(url) > 500) then raise exception 'Tracking link must start with http:// or https://'; end if;
  if tno is not null and length(tno) > 80 then raise exception 'Tracking number is too long'; end if;
  with u as (update public.restock_orders set status = 'shipped', shipped_at = now(), ship_date = p_date, shipped_by_name = me, updated_at = now()
      where box_no = p_box and status = 'added' and supplier = idn returning *),
    e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'shipped', coalesce(ship_qty, qty), p_box from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'This box is empty'; end if;
  update public.restock_boxes set status = 'shipped', shipped_at = now(), ship_date = p_date, tracking_url = url, tracking_no = tno where box_no = p_box;
  return n;
end $$;

create function public.restock_supplier_tracking(p_box text, p_url text, p_no text) returns void
language plpgsql security definer set search_path = '' as $$
declare c text; url text := nullif(btrim(coalesce(p_url, '')), ''); tno text := nullif(btrim(coalesce(p_no, '')), '');
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  if url is not null and (url !~ '^https?://' or length(url) > 500) then raise exception 'Tracking link must start with http:// or https://'; end if;
  if tno is not null and length(tno) > 80 then raise exception 'Tracking number is too long'; end if;
  update public.restock_boxes set tracking_url = url, tracking_no = tno where box_no = p_box and code = c;
  if not found then raise exception 'Unknown box'; end if;
end $$;

-- quantity changes only on the supplier's own lines that are in an open box
create or replace function public.restock_supplier_set_qty(p_id text, p_qty integer) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  with old as (select id, coalesce(ship_qty, qty) as was from public.restock_orders
                 where id = p_id and claimed and supplier = idn and status = 'added' and p_qty is not null for update),
       u as (update public.restock_orders o set ship_qty = case when p_qty >= o.qty then null else greatest(p_qty, 0) end,
                    qty_by_name = case when p_qty >= o.qty then null else me end, updated_at = now()
             from old where o.id = old.id returning o.*, old.was)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
    select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'qty', was, coalesce(ship_qty, qty) from u where was is distinct from coalesce(ship_qty, qty);
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.restock_my_code(), public.restock_supplier_state(), public.restock_supplier_add(text[], text), public.restock_supplier_remove(text[]),
  public.restock_supplier_new_box(), public.restock_supplier_ship_box(text, date, text, text), public.restock_supplier_tracking(text, text, text) from public, anon, authenticated;
grant execute on function public.restock_my_code(), public.restock_supplier_state(), public.restock_supplier_add(text[], text), public.restock_supplier_remove(text[]),
  public.restock_supplier_new_box(), public.restock_supplier_ship_box(text, date, text, text), public.restock_supplier_tracking(text, text, text) to authenticated, service_role;
-- the older single-step supplier functions are replaced by the box functions above
revoke all on function public.restock_supplier_act(text, text[]), public.restock_supplier_ship(text[], date), public.restock_supplier_list(), public.restock_next_box() from public, anon, authenticated;
