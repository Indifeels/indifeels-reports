-- A PDF order is ORDERED (not shipped) until the owner marks it shipped. While ordered its lines stay status 'saved'
-- (so they count as ordered everywhere) but are claimed by the file, which takes them off the Order list and hides them from other suppliers.
-- "Mark shipped" turns them into a shipped box with the file code, which is then received like any box.

alter table public.restock_exports add column shipped_at timestamptz;

-- put the file already made (PDF-IN1-01) back to Ordered
update public.restock_orders set status = 'saved', claimed = true, shipped_at = null, ship_date = null, ship_qty = null, shipped_by_name = null, updated_at = now()
 where box_no = 'PDF-IN1-01' and status = 'shipped' and coalesce(recv_qty, 0) = 0;
delete from public.restock_events where box_no = 'PDF-IN1-01' and action = 'shipped';
delete from public.restock_boxes where box_no = 'PDF-IN1-01';

create or replace function public.restock_owner_export_create(p_supplier text, p_ids text[]) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); sup text := btrim(coalesce(p_supplier, '')); c text; n integer; sq integer; cd text;
        words text[]; letters text; rows jsonb; units integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if sup = '' or length(sup) > 100 then raise exception 'Pick a supplier'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 1000 then raise exception 'Nothing to export'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));

  select code into c from public.restock_supplier_codes where identity = sup;
  if c is null then
    words := regexp_split_to_array(btrim(regexp_replace(sup, '[^A-Za-z0-9 ]', '', 'g')), '\s+');
    letters := upper(left(coalesce(words[1], 'X'), 1) || case when array_length(words, 1) > 1 then left(words[2], 1) else '' end);
    c := letters || (1 + (select count(*) from public.restock_supplier_codes where code ~ ('^' || letters || '[0-9]+$')));
    insert into public.restock_supplier_codes(identity, code) values (sup, c);
  end if;
  select coalesce(max(seq), 0) + 1 into sq from public.restock_exports where sup_code = c;
  cd := 'PDF-' || c || '-' || lpad(sq::text, 2, '0');

  with u as (
    update public.restock_orders o
       set claimed = true, box_no = cd, updated_at = now()
     where o.id = any(p_ids) and o.status = 'saved' and not o.claimed
     returning o.id, o.product_title, o.image, o.variant_title, o.supplier, o.qty),
  ev as (
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'ordered', qty, cd from u returning 1)
  select coalesce(jsonb_agg(jsonb_build_object('id', u.id, 'product', u.product_title, 'image', u.image, 'size', u.variant_title, 'qty', u.qty) order by array_position(p_ids, u.id)), '[]'::jsonb),
         coalesce(sum(u.qty), 0)
    into rows, units from u;
  n := jsonb_array_length(rows);
  if n = 0 then raise exception 'Nothing on the order list to export (already exported or no longer waiting)'; end if;

  insert into public.restock_exports(code, supplier, sup_code, seq, lines, units, created_by_name, ship_date) values (cd, sup, c, sq, rows, units, me, null);
  return jsonb_build_object('code', cd, 'supplier', sup, 'lines', rows, 'units', units, 'skipped', array_length(p_ids, 1) - n);
end $$;

create or replace function public.restock_owner_export_list() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.created_at desc) from (
    select e.code, e.supplier, e.status, e.units, e.created_at, e.created_by_name, e.shipped_at, jsonb_array_length(e.lines) as n,
           (select coalesce(jsonb_agg(l.v || jsonb_build_object('pid', o.product_id) order by l.ord), '[]'::jsonb)
              from jsonb_array_elements(e.lines) with ordinality as l(v, ord)
              left join public.restock_orders o on o.id = l.v->>'id') as lines
    from public.restock_exports e where e.status = 'sent' and e.created_at > now() - interval '120 days') x), '[]'::jsonb);
end $$;

-- "Mark shipped": the ordered lines become a shipped box with the file code
create function public.restock_owner_export_shipped(p_code text, p_date date) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); e public.restock_exports; n integer; d date := coalesce(p_date, current_date);
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if d > current_date + 1 or d < current_date - 30 then raise exception 'Shipped date must be within the last 30 days'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));
  select * into e from public.restock_exports where code = p_code for update;
  if e.code is null or e.status <> 'sent' then raise exception 'File not found'; end if;
  if e.shipped_at is not null then raise exception '% is already marked shipped', e.code; end if;
  with u as (
    update public.restock_orders o
       set status = 'shipped', shipped_at = now(), ship_date = d, ship_qty = o.qty, shipped_by_name = me, updated_at = now()
     where o.box_no = e.code and o.status = 'saved' and o.claimed
     returning o.id, o.product_title, o.variant_title, o.supplier, o.qty),
  ev as (
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'shipped', qty, e.code from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'None of these lines are still ordered, so nothing was marked shipped'; end if;
  insert into public.restock_boxes(box_no, code, seq, supplier, status, shipped_at, ship_date) values (e.code, 'PDF-' || e.sup_code, e.seq, e.supplier, 'shipped', now(), d);
  update public.restock_exports set shipped_at = now(), ship_date = d where code = e.code;
  return jsonb_build_object('code', e.code, 'shipped', n);
end $$;

-- exported by mistake: back to the Order list (only while nothing has been received)
create or replace function public.restock_owner_export_cancel(p_code text) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));
  if not exists (select 1 from public.restock_exports where code = p_code and status = 'sent') then raise exception 'File not found'; end if;
  if exists (select 1 from public.restock_orders where box_no = p_code and (coalesce(recv_qty, 0) > 0 or status = 'received')) then
    raise exception 'Some of % has already been received, so it can''t be cancelled. Use the box receive instead.', p_code;
  end if;
  update public.restock_orders set status = 'saved', claimed = false, box_no = null, shipped_at = null, ship_date = null, ship_qty = null, shipped_by_name = null, updated_at = now()
   where box_no = p_code and status in ('saved', 'shipped');
  get diagnostics n = row_count;
  delete from public.restock_boxes where box_no = p_code;
  update public.restock_exports set status = 'cancelled' where code = p_code;
  return n;
end $$;

revoke all on function public.restock_owner_export_shipped(text, date) from public, anon;
grant execute on function public.restock_owner_export_shipped(text, date) to authenticated;
