-- PDF (Excel) orders: every exported order file gets its own code (PDF-IN1-01), like a box code (Box-P1-01).
-- Exporting moves the supplier's order-list lines straight into a shipped box with that code, so the Order list clears,
-- and receiving / printing barcodes / cross-checking / "not received goes back to the Order list" work exactly like a supplier box.
-- Supplier short codes live in restock_supplier_codes (P1 = Pankaj, V1 = Vistara). New suppliers get initials + number: Indian Needle -> IN1.

create table public.restock_exports(
  code text primary key,                                   -- PDF-IN1-01
  supplier text not null check (length(supplier) between 1 and 100),
  sup_code text not null,                                  -- IN1
  seq integer not null,
  status text not null default 'sent' check (status in ('sent','cancelled')),
  lines jsonb not null,                                    -- snapshot: [{id, product, image, size, qty}]
  units integer not null default 0,
  created_at timestamptz not null default now(),
  created_by_name text not null default '',
  ship_date date,
  unique (sup_code, seq)
);
alter table public.restock_exports enable row level security;   -- no policies: functions only
grant all on public.restock_exports to service_role;

-- 1) export: new file code, lines leave the Order list and become a shipped box with that code
create function public.restock_owner_export_create(p_supplier text, p_ids text[]) returns jsonb
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
       set status = 'shipped', shipped_at = now(), ship_date = current_date, box_no = cd,
           ship_qty = o.qty, shipped_by_name = me, updated_at = now()
     where o.id = any(p_ids) and o.status = 'saved' and not o.claimed
     returning o.id, o.product_title, o.image, o.variant_title, o.supplier, o.qty),
  ev as (
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'shipped', qty, cd from u returning 1)
  select coalesce(jsonb_agg(jsonb_build_object('id', u.id, 'product', u.product_title, 'image', u.image, 'size', u.variant_title, 'qty', u.qty) order by array_position(p_ids, u.id)), '[]'::jsonb),
         coalesce(sum(u.qty), 0)
    into rows, units from u;
  n := jsonb_array_length(rows);
  if n = 0 then raise exception 'Nothing on the order list to export (already exported or no longer waiting)'; end if;

  insert into public.restock_exports(code, supplier, sup_code, seq, lines, units, created_by_name, ship_date) values (cd, sup, c, sq, rows, units, me, current_date);
  insert into public.restock_boxes(box_no, code, seq, supplier, status, shipped_at, ship_date) values (cd, 'PDF-' || c, sq, sup, 'shipped', now(), current_date);
  return jsonb_build_object('code', cd, 'supplier', sup, 'lines', rows, 'units', units, 'skipped', array_length(p_ids, 1) - n);
end $$;

-- 2) recent files (for "Download again")
create function public.restock_owner_export_list() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.created_at desc) from (
    select e.code, e.supplier, e.status, e.units, e.created_at, e.created_by_name, jsonb_array_length(e.lines) as n, e.lines
    from public.restock_exports e where e.status = 'sent' and e.created_at > now() - interval '120 days') x), '[]'::jsonb);
end $$;

-- 3) exported by mistake: put the lines back on the Order list (only while nothing from the file has been received)
create function public.restock_owner_export_cancel(p_code text) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));
  if not exists (select 1 from public.restock_exports where code = p_code and status = 'sent') then raise exception 'File not found'; end if;
  if exists (select 1 from public.restock_orders where box_no = p_code and (recv_qty > 0 or status = 'received')) then
    raise exception 'Some of % has already been received, so it can''t be cancelled. Use the box receive instead.', p_code;
  end if;
  update public.restock_orders set status = 'saved', box_no = null, shipped_at = null, ship_date = null, ship_qty = null, shipped_by_name = null, updated_at = now()
   where box_no = p_code and status = 'shipped';
  get diagnostics n = row_count;
  delete from public.restock_boxes where box_no = p_code;
  update public.restock_exports set status = 'cancelled' where code = p_code;
  return n;
end $$;

revoke all on function public.restock_owner_export_create(text, text[]), public.restock_owner_export_list(), public.restock_owner_export_cancel(text) from public, anon;
grant execute on function public.restock_owner_export_create(text, text[]), public.restock_owner_export_list(), public.restock_owner_export_cancel(text) to authenticated;
