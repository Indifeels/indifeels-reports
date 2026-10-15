-- Who did what: every order, box, quantity change, shipment and restock is recorded with the person's name and time.
-- Run AFTER 20261015140000_restock_supplier_shipping.sql.
alter table public.restock_orders
  add column added_by_name text, add column shipped_by_name text, add column qty_by_name text;

create table public.restock_events(
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  order_id text not null,
  label text not null default '',            -- "<product> · <variant>"
  supplier text not null default '',
  actor uuid default auth.uid(),
  actor_name text not null default '',
  actor_role text not null default '',       -- 'owner' | 'supplier'
  action text not null check (action in ('ordered','unordered','boxed','unboxed','qty','shipped','received')),
  qty_from integer, qty_to integer, box_no text
);
create index restock_events_at_idx on public.restock_events(at desc);
alter table public.restock_events enable row level security;
grant select on public.restock_events to authenticated;
grant all on public.restock_events to service_role;
create policy restock_events_owner_read on public.restock_events for select to authenticated using ((select public.can_view('restock-plan')));

create function public.restock_actor() returns text language sql stable security definer set search_path = '' as $$
  select coalesce(nullif(btrim(p.display_name), ''), p.username, 'unknown') from public.profiles p where p.id = auth.uid()
$$;
revoke all on function public.restock_actor() from public, anon;
grant execute on function public.restock_actor() to authenticated, service_role;

create or replace function public.restock_owner_save(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; rid text := p->>'id'; q integer := coalesce((p->>'qty')::integer, 0); me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if rid is null or length(rid) > 120 then raise exception 'Bad id'; end if;
  if q <= 0 then
    with d as (delete from public.restock_orders where id = rid and status in ('saved','received') returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
      select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unordered', qty, 0 from d where status = 'saved';
    return null;
  end if;
  insert into public.restock_orders(id, product_id, product_title, image, variant_title, supplier, qty, stock_base, saved_by)
  values (rid, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          left(coalesce(p->>'supplier',''), 100), q, nullif(p->>'stock_base','')::integer, auth.uid())
  on conflict (id) do update
    set qty = excluded.qty, product_title = excluded.product_title, image = excluded.image, supplier = excluded.supplier,
        stock_base = case when public.restock_orders.status = 'received' then excluded.stock_base else coalesce(excluded.stock_base, public.restock_orders.stock_base) end,
        status = 'saved', ship_qty = case when public.restock_orders.status = 'saved' and public.restock_orders.ship_qty < excluded.qty then public.restock_orders.ship_qty else null end,
        added_at = null, shipped_at = null, ship_date = null, box_no = null, received_at = null,
        added_by_name = null, shipped_by_name = null, qty_by_name = null,
        saved_at = case when public.restock_orders.status = 'received' then now() else public.restock_orders.saved_at end,
        updated_at = now()
    where public.restock_orders.status in ('saved','received')
  returning * into r;
  if r.id is null then raise exception 'This item is already with the supplier and cannot be changed'; end if;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', r.qty);
  return r;
end $$;

create or replace function public.restock_owner_received(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  with u as (update public.restock_orders set status = 'received', received_at = now(), updated_at = now()
    where id = any(p_ids) and status = 'shipped' returning *)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'received', coalesce(ship_qty, qty) from u;
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function public.restock_supplier_act(p_action text, p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if p_action = 'add' then
    with u as (update public.restock_orders set status = 'added', added_at = now(), added_by_name = me, updated_at = now()
      where (s is null or supplier = s) and id = any(p_ids) and status = 'saved' returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
      select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'boxed', coalesce(ship_qty, qty) from u;
  elsif p_action = 'unadd' then
    with u as (update public.restock_orders set status = 'saved', added_at = null, added_by_name = null, updated_at = now()
      where (s is null or supplier = s) and id = any(p_ids) and status = 'added' returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action)
      select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'unboxed' from u;
  else
    raise exception 'Bad action';
  end if;
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function public.restock_supplier_set_qty(p_id text, p_qty integer) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  with old as (select id, coalesce(ship_qty, qty) as was from public.restock_orders
                 where id = p_id and (s is null or supplier = s) and status in ('saved','added') and p_qty is not null for update),
       u as (update public.restock_orders o set ship_qty = case when p_qty >= o.qty then null else greatest(p_qty, 0) end,
                    qty_by_name = case when p_qty >= o.qty then null else me end, updated_at = now()
             from old where o.id = old.id returning o.*, old.was)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
    select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'qty', was, coalesce(ship_qty, qty) from u where was is distinct from coalesce(ship_qty, qty);
  get diagnostics n = row_count;
  return n;
end $$;

create or replace function public.restock_supplier_ship(p_ids text[], p_box text, p_date date) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer; box text := btrim(coalesce(p_box, '')); me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if box = '' or length(box) > 40 then raise exception 'Enter a box number'; end if;
  if p_date is null or p_date > current_date + 1 or p_date < current_date - 30 then raise exception 'Ship date must be within the last 30 days'; end if;
  with u as (update public.restock_orders set status = 'shipped', shipped_at = now(), ship_date = p_date, box_no = box, shipped_by_name = me, updated_at = now()
    where (s is null or supplier = s) and id = any(p_ids) and status = 'added' returning *)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
    select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'shipped', coalesce(ship_qty, qty), box from u;
  get diagnostics n = row_count;
  return n;
end $$;
