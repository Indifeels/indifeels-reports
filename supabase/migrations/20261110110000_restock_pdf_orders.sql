-- PDF (Excel) orders: every exported order file gets its own code (PDF-IN1-01), like a box code (Box-P1-01).
-- The owner confirms which file was actually sent ("I sent this file"); the lines then become a shipped box with
-- that code, so receiving / printing barcodes / cross-checking works exactly like a supplier box.
-- Supplier short codes live in restock_supplier_codes (P1 = Pankaj, V1 = Vistara). New suppliers get initials + number: Indian Needle -> IN1.

create table public.restock_exports(
  code text primary key,                                   -- PDF-IN1-01
  supplier text not null check (length(supplier) between 1 and 100),
  sup_code text not null,                                  -- IN1
  seq integer not null,
  status text not null default 'pending' check (status in ('pending','sent','discarded')),
  lines jsonb not null,                                    -- snapshot: [{id, product, image, size, qty}]
  units integer not null default 0,
  created_at timestamptz not null default now(),
  created_by_name text not null default '',
  sent_at timestamptz,
  sent_by_name text,
  ship_date date,
  boxed integer,                                           -- lines that went into the box when it was marked sent
  unique (sup_code, seq)
);
alter table public.restock_exports enable row level security;   -- no policies: functions only
grant all on public.restock_exports to service_role;

-- 1) create an export file code for a supplier's order-list lines
create function public.restock_owner_export_create(p_supplier text, p_ids text[]) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); sup text := btrim(coalesce(p_supplier, '')); c text; n integer; sq integer; cd text;
        words text[]; letters text; rows jsonb; units integer; skipped integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if sup = '' or length(sup) > 100 then raise exception 'Pick a supplier'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 1000 then raise exception 'Nothing to export'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));

  -- lines still waiting on the order list and not already in another pending file
  select coalesce(jsonb_agg(jsonb_build_object('id', o.id, 'product', o.product_title, 'image', o.image, 'size', o.variant_title, 'qty', o.qty) order by x.ord), '[]'::jsonb),
         coalesce(sum(o.qty), 0)
    into rows, units
    from unnest(p_ids) with ordinality as x(id, ord)
    join public.restock_orders o on o.id = x.id
   where o.status = 'saved' and not o.claimed
     and not exists (select 1 from public.restock_exports e where e.status = 'pending' and e.lines @> jsonb_build_array(jsonb_build_object('id', o.id)));
  n := jsonb_array_length(rows);
  skipped := array_length(p_ids, 1) - n;
  if n = 0 then raise exception 'Everything on this list is already in a PDF order waiting to be marked sent (or is no longer on the order list)'; end if;

  select code into c from public.restock_supplier_codes where identity = sup;
  if c is null then
    words := regexp_split_to_array(btrim(regexp_replace(sup, '[^A-Za-z0-9 ]', '', 'g')), '\s+');
    letters := upper(left(coalesce(words[1], 'X'), 1) || case when array_length(words, 1) > 1 then left(words[2], 1) else '' end);
    c := letters || (1 + (select count(*) from public.restock_supplier_codes where code ~ ('^' || letters || '[0-9]+$')));
    insert into public.restock_supplier_codes(identity, code) values (sup, c);
  end if;
  select coalesce(max(seq), 0) + 1 into sq from public.restock_exports where sup_code = c;
  cd := 'PDF-' || c || '-' || lpad(sq::text, 2, '0');
  insert into public.restock_exports(code, supplier, sup_code, seq, lines, units, created_by_name) values (cd, sup, c, sq, rows, units, me);
  return jsonb_build_object('code', cd, 'supplier', sup, 'lines', rows, 'units', units, 'skipped', skipped);
end $$;

-- 2) list files waiting to be confirmed + recently sent ones
create function public.restock_owner_export_list() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.created_at desc) from (
    select e.code, e.supplier, e.status, e.units, e.created_at, e.created_by_name, e.sent_at, e.boxed,
           jsonb_array_length(e.lines) as n, case when e.status = 'pending' then e.lines else '[]'::jsonb end as lines
    from public.restock_exports e
    where e.status = 'pending' or (e.status = 'sent' and e.sent_at > now() - interval '90 days')) x), '[]'::jsonb);
end $$;

-- 3) "I sent this file": the file's lines become a shipped box with the same code
create function public.restock_owner_export_sent(p_code text, p_date date) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare me text := public.restock_actor(); e public.restock_exports; l jsonb; n integer := 0; ship integer; d date := coalesce(p_date, current_date);
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if d > current_date + 1 or d < current_date - 30 then raise exception 'Sent date must be within the last 30 days'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_export'));
  select * into e from public.restock_exports where code = p_code for update;
  if e.code is null then raise exception 'Unknown file code'; end if;
  if e.status <> 'pending' then raise exception '% is already %', e.code, e.status; end if;
  for l in select * from jsonb_array_elements(e.lines) loop
    with u as (
      update public.restock_orders o
         set status = 'shipped', shipped_at = now(), ship_date = d, box_no = e.code,
             ship_qty = least((l->>'qty')::integer, o.qty), shipped_by_name = me, updated_at = now()
       where o.id = l->>'id' and o.status = 'saved' and not o.claimed
       returning o.id, o.product_title, o.variant_title, o.supplier, coalesce(o.ship_qty, o.qty) as q)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'shipped', q, e.code from u;
    get diagnostics ship = row_count; n := n + ship;
  end loop;
  if n = 0 then raise exception 'None of these lines are on the order list any more, so nothing was marked sent'; end if;
  insert into public.restock_boxes(box_no, code, seq, supplier, status, shipped_at, ship_date) values (e.code, 'PDF-' || e.sup_code, e.seq, e.supplier, 'shipped', now(), d);
  update public.restock_exports set status = 'sent', sent_at = now(), sent_by_name = me, ship_date = d, boxed = n where code = e.code;
  return jsonb_build_object('code', e.code, 'boxed', n, 'skipped', jsonb_array_length(e.lines) - n);
end $$;

-- 4) throw a file away (it was never sent): its lines stay on the order list
create function public.restock_owner_export_discard(p_code text) returns boolean
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  update public.restock_exports set status = 'discarded' where code = p_code and status = 'pending';
  return found;
end $$;

revoke all on function public.restock_owner_export_create(text, text[]), public.restock_owner_export_list(), public.restock_owner_export_sent(text, date), public.restock_owner_export_discard(text) from public, anon;
grant execute on function public.restock_owner_export_create(text, text[]), public.restock_owner_export_list(), public.restock_owner_export_sent(text, date), public.restock_owner_export_discard(text) to authenticated;
