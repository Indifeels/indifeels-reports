-- 1) Top-ups: one variant can have several order batches in progress (each batch is its own row for the supplier).
-- 2) Automatic box numbers per supplier: Box-P1-01, Box-P1-02 ...
-- 3) Discontinued flag: set in the planner, pushed to the Shopify metafield custom.discountinued by the next build.
-- Run AFTER 20261015150000_restock_audit.sql.

alter table public.restock_orders add column vkey text;      -- "<product id>|<variant title>", shared by every batch of a variant
update public.restock_orders set vkey = id where vkey is null;
create index restock_orders_vkey_idx on public.restock_orders(vkey);
create sequence public.restock_batch_seq;

-- new batch for a variant (never changes an existing batch)
create function public.restock_owner_order(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; vk text := p->>'vkey'; q integer := coalesce((p->>'qty')::integer, 0); me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if vk is null or length(vk) > 100 then raise exception 'Bad id'; end if;
  if q <= 0 or q > 100000 then raise exception 'Quantity must be at least 1'; end if;
  insert into public.restock_orders(id, vkey, product_id, product_title, image, variant_title, supplier, qty, stock_base, saved_by)
  values (vk || '#' || nextval('public.restock_batch_seq'), vk, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          left(coalesce(p->>'supplier',''), 100), q, nullif(p->>'stock_base','')::integer, auth.uid())
  returning * into r;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', r.qty);
  return r;
end $$;

-- cancel a batch the supplier has not boxed yet
create function public.restock_owner_cancel(p_id text) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer; me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  with d as (delete from public.restock_orders where id = p_id and status = 'saved' returning *)
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to)
    select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unordered', qty, 0 from d;
  get diagnostics n = row_count;
  return n;
end $$;
drop function public.restock_owner_save(jsonb);

-- supplier list now carries the batch date and variant key
drop function public.restock_supplier_list();
create function public.restock_supplier_list() returns table(id text, vkey text, product_id text, image text, variant_title text, qty integer, ship_qty integer, status text, saved_at timestamptz, added_at timestamptz, shipped_at timestamptz, box_no text, ship_date date, supplier text)
language plpgsql stable security definer set search_path = '' as $$
declare s text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  return query
    select o.id, o.vkey, o.product_id, o.image, o.variant_title, o.qty, o.ship_qty, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.supplier
    from public.restock_orders o
    where (s is null or o.supplier = s) and (o.status in ('saved','added') or o.shipped_at > now() - interval '60 days')
    order by o.product_id, o.variant_title, o.saved_at;
end $$;

-- ---------- automatic box numbers ----------
create table public.restock_supplier_codes(identity text primary key, code text not null unique);
create table public.restock_boxes(box_no text primary key, code text not null, seq integer not null, created_at timestamptz not null default now(), created_by uuid default auth.uid(), unique(code, seq));
alter table public.restock_supplier_codes enable row level security;
alter table public.restock_boxes enable row level security;
grant all on public.restock_supplier_codes, public.restock_boxes to service_role;

-- who is shipping: the supplier name the login is linked to, otherwise the login's own name
create function public.restock_box_identity() returns text language sql stable security definer set search_path = '' as $$
  select coalesce((select u.supplier from public.restock_supplier_users u where u.user_id = auth.uid()), public.restock_actor(), 'X')
$$;

create function public.restock_next_box() returns text
language plpgsql stable security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; n integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select code into c from public.restock_supplier_codes where identity = idn;
  if c is null then
    c := upper(coalesce(nullif(substr(regexp_replace(idn, '[^A-Za-z0-9]', '', 'g'), 1, 1), ''), 'X'))
         || (1 + (select count(*) from public.restock_supplier_codes where code ~ ('^' || upper(coalesce(nullif(substr(regexp_replace(idn, '[^A-Za-z0-9]', '', 'g'), 1, 1), ''), 'X')) || '[0-9]+$')));
  end if;
  select coalesce(max(seq), 0) + 1 into n from public.restock_boxes where code = c;
  return 'Box-' || c || '-' || lpad(n::text, 2, '0');
end $$;

drop function public.restock_supplier_ship(text[], text, date);
create function public.restock_supplier_ship(p_ids text[], p_date date) returns text
language plpgsql security definer set search_path = '' as $$
declare s text; n integer; idn text := public.restock_box_identity(); c text; seq integer; box text; me text := public.restock_actor();
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if p_date is null or p_date > current_date + 1 or p_date < current_date - 30 then raise exception 'Ship date must be within the last 30 days'; end if;
  perform pg_advisory_xact_lock(hashtext('restock_box'));
  select code into c from public.restock_supplier_codes where identity = idn;
  if c is null then
    c := upper(coalesce(nullif(substr(regexp_replace(idn, '[^A-Za-z0-9]', '', 'g'), 1, 1), ''), 'X'))
         || (1 + (select count(*) from public.restock_supplier_codes where code ~ ('^' || upper(coalesce(nullif(substr(regexp_replace(idn, '[^A-Za-z0-9]', '', 'g'), 1, 1), ''), 'X')) || '[0-9]+$')));
    insert into public.restock_supplier_codes(identity, code) values (idn, c);
  end if;
  select coalesce(max(b.seq), 0) + 1 into seq from public.restock_boxes b where b.code = c;
  box := 'Box-' || c || '-' || lpad(seq::text, 2, '0');
  with u as (update public.restock_orders set status = 'shipped', shipped_at = now(), ship_date = p_date, box_no = box, shipped_by_name = me, updated_at = now()
    where (s is null or supplier = s) and id = any(p_ids) and status = 'added' returning *),
       e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
         select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'shipped', coalesce(ship_qty, qty), box from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'Nothing is in the box to ship'; end if;
  insert into public.restock_boxes(box_no, code, seq) values (box, c, seq);
  return box;
end $$;

-- ---------- discontinued ----------
create table public.restock_discontinued(
  product_id text primary key check (product_id ~ '^[0-9]{1,20}$'),
  discontinued boolean not null,
  requested_by uuid default auth.uid(),
  requested_by_name text,
  requested_at timestamptz not null default now(),
  synced_at timestamptz                         -- set once the Shopify metafield has been updated
);
alter table public.restock_discontinued enable row level security;
grant select on public.restock_discontinued to authenticated;
grant all on public.restock_discontinued to service_role;
create policy restock_disc_read on public.restock_discontinued for select to authenticated using ((select public.can_view('restock-plan')));

create function public.restock_owner_set_discontinued(p_product text, p_value boolean) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  insert into public.restock_discontinued(product_id, discontinued, requested_by_name) values (p_product, p_value, public.restock_actor())
  on conflict (product_id) do update set discontinued = excluded.discontinued, requested_by = auth.uid(), requested_by_name = excluded.requested_by_name, requested_at = now(), synced_at = null;
end $$;

-- called by the GitHub build (read token) to push changes to Shopify, then mark them done
create function public.sync_get_restock_discontinued(p_token text) returns table(product_id text, discontinued boolean)
language plpgsql security definer set search_path = '' as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select d.product_id, d.discontinued from public.restock_discontinued d where d.synced_at is null;
end $$;
create function public.sync_mark_restock_discontinued(p_token text, p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  update public.restock_discontinued set synced_at = now() where product_id = any(p_ids) and synced_at is null;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.restock_owner_order(jsonb), public.restock_owner_cancel(text), public.restock_supplier_list(), public.restock_box_identity(), public.restock_next_box(),
  public.restock_supplier_ship(text[], date), public.restock_owner_set_discontinued(text, boolean), public.sync_get_restock_discontinued(text), public.sync_mark_restock_discontinued(text, text[]) from public, anon, authenticated;
grant execute on function public.restock_owner_order(jsonb), public.restock_owner_cancel(text), public.restock_supplier_list(), public.restock_next_box(),
  public.restock_supplier_ship(text[], date), public.restock_owner_set_discontinued(text, boolean) to authenticated, service_role;
grant execute on function public.restock_box_identity() to authenticated, service_role;
grant execute on function public.sync_get_restock_discontinued(text), public.sync_mark_restock_discontinued(text, text[]) to anon, authenticated, service_role;
