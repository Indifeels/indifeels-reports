-- Supplier can report what they can actually ship (ship_qty), and must give a box number and ship date when shipping.
-- Owner keeps the full timeline: ordered -> in box -> shipped -> restocked, and sees a low-stock flag when ship_qty < qty.
alter table public.restock_orders
  add column ship_qty integer check (ship_qty is null or (ship_qty >= 0 and ship_qty <= 100000)),
  add column box_no text check (box_no is null or length(box_no) between 1 and 40),
  add column ship_date date,
  add column stock_base integer,                 -- website stock when the owner saved the order (used to detect the restock)
  add column received_at timestamptz;
alter table public.restock_orders drop constraint restock_orders_status_check;
alter table public.restock_orders add constraint restock_orders_status_check check (status in ('saved','added','shipped','received'));

-- owner: (re)ordering resets a line that is saved or already restocked; supplier-held lines stay locked
create or replace function public.restock_owner_save(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; rid text := p->>'id'; q integer := coalesce((p->>'qty')::integer, 0);
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if rid is null or length(rid) > 120 then raise exception 'Bad id'; end if;
  if q <= 0 then
    delete from public.restock_orders where id = rid and status in ('saved','received');
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
        saved_at = case when public.restock_orders.status = 'received' then now() else public.restock_orders.saved_at end,
        updated_at = now()
    where public.restock_orders.status in ('saved','received')
  returning * into r;
  if r.id is null then raise exception 'This item is already with the supplier and cannot be changed'; end if;
  return r;
end $$;

-- owner: stock arrived -> stop the timer (keeps the line for history)
create or replace function public.restock_owner_received(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  update public.restock_orders set status = 'received', received_at = now(), updated_at = now()
    where id = any(p_ids) and status = 'shipped';
  get diagnostics n = row_count;
  return n;
end $$;

-- supplier list: pending + recently shipped/received (return type changes, so drop first)
drop function public.restock_supplier_list();
create function public.restock_supplier_list() returns table(id text, product_id text, image text, variant_title text, qty integer, ship_qty integer, status text, added_at timestamptz, shipped_at timestamptz, box_no text, ship_date date, supplier text)
language plpgsql stable security definer set search_path = '' as $$
declare s text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  return query
    select o.id, o.product_id, o.image, o.variant_title, o.qty, o.ship_qty, o.status, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.supplier
    from public.restock_orders o
    where (s is null or o.supplier = s) and (o.status in ('saved','added') or o.shipped_at > now() - interval '60 days')
    order by o.product_id, o.variant_title;
end $$;

-- supplier: add / remove from box only (shipping has its own function that requires a box number and date)
create or replace function public.restock_supplier_act(p_action text, p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if p_action = 'add' then
    update public.restock_orders set status = 'added', added_at = now(), updated_at = now()
      where (s is null or supplier = s) and id = any(p_ids) and status = 'saved';
  elsif p_action = 'unadd' then
    update public.restock_orders set status = 'saved', added_at = null, updated_at = now()
      where (s is null or supplier = s) and id = any(p_ids) and status = 'added';
  else
    raise exception 'Bad action';
  end if;
  get diagnostics n = row_count;
  return n;
end $$;

-- supplier: how many they can actually ship (0..ordered)
create function public.restock_supplier_set_qty(p_id text, p_qty integer) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  update public.restock_orders set ship_qty = case when p_qty >= qty then null else greatest(p_qty, 0) end, updated_at = now()
    where id = p_id and (s is null or supplier = s) and status in ('saved','added') and p_qty is not null;
  get diagnostics n = row_count;
  return n;
end $$;

-- supplier: ship boxed items with a box number and ship date
create function public.restock_supplier_ship(p_ids text[], p_box text, p_date date) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer; box text := btrim(coalesce(p_box, ''));
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if box = '' or length(box) > 40 then raise exception 'Enter a box number'; end if;
  if p_date is null or p_date > current_date + 1 or p_date < current_date - 30 then raise exception 'Ship date must be within the last 30 days'; end if;
  update public.restock_orders set status = 'shipped', shipped_at = now(), ship_date = p_date, box_no = box, updated_at = now()
    where (s is null or supplier = s) and id = any(p_ids) and status = 'added';
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.restock_supplier_list(), public.restock_supplier_act(text, text[]), public.restock_supplier_set_qty(text, integer),
  public.restock_supplier_ship(text[], text, date), public.restock_owner_save(jsonb), public.restock_owner_received(text[]) from public, anon;
grant execute on function public.restock_supplier_list(), public.restock_supplier_act(text, text[]), public.restock_supplier_set_qty(text, integer),
  public.restock_supplier_ship(text[], text, date), public.restock_owner_save(jsonb), public.restock_owner_received(text[]) to authenticated, service_role;
