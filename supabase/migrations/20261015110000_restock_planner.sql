-- Restock Planner: owner plans quantities, supplier packs and ships them.
-- Owner side  : report "restock-plan"     (admin only)  -> reads the table, writes only through restock_owner_* functions.
-- Supplier side: report "restock-supplier" (grantable)   -> no table access at all, only restock_supplier_* functions,
--                and only for the supplier name the account is linked to in restock_supplier_users.

create table public.restock_orders(
  id text primary key check (length(id) <= 120),            -- "<product id>|<variant title>"
  product_id text not null check (length(product_id) <= 30),
  product_title text not null default '' check (length(product_title) <= 300),
  image text not null default '' check (image = '' or image ~ '^https://cdn\.shopify\.com/'),
  variant_title text not null check (length(variant_title) <= 120),
  supplier text not null check (length(supplier) between 1 and 100),
  qty integer not null check (qty > 0 and qty <= 100000),
  status text not null default 'saved' check (status in ('saved','added','shipped')),
  saved_at timestamptz not null default now(),
  added_at timestamptz,
  shipped_at timestamptz,
  saved_by uuid default auth.uid(),
  updated_at timestamptz not null default now()
);
create index restock_orders_supplier_idx on public.restock_orders(supplier, status);
alter table public.restock_orders enable row level security;
grant select on public.restock_orders to authenticated;
grant all on public.restock_orders to service_role;
create policy restock_orders_owner_read on public.restock_orders for select to authenticated
  using ((select public.can_view('restock-plan')));

create table public.restock_supplier_users(
  user_id uuid primary key references public.profiles(id) on delete cascade,
  supplier text not null check (length(supplier) between 1 and 100)
);
alter table public.restock_supplier_users enable row level security;   -- no policies: functions only
grant all on public.restock_supplier_users to service_role;

-- ---------- owner ----------
create function public.restock_owner_save(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; rid text := p->>'id'; q integer := coalesce((p->>'qty')::integer, 0);
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if rid is null or length(rid) > 120 then raise exception 'Bad id'; end if;
  if q <= 0 then
    delete from public.restock_orders where id = rid and status = 'saved';
    return null;
  end if;
  insert into public.restock_orders(id, product_id, product_title, image, variant_title, supplier, qty, saved_by)
  values (rid, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          left(coalesce(p->>'supplier',''), 100), q, auth.uid())
  on conflict (id) do update
    set qty = excluded.qty, product_title = excluded.product_title, image = excluded.image,
        supplier = excluded.supplier, updated_at = now()
    where public.restock_orders.status = 'saved'
  returning * into r;
  if r.id is null then raise exception 'This item is already with the supplier and cannot be changed'; end if;
  return r;
end $$;

create function public.restock_owner_received(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  delete from public.restock_orders where id = any(p_ids) and status = 'shipped';
  get diagnostics n = row_count;
  return n;
end $$;

-- people list for the "Supplier accounts" panel (admin only)
create function public.restock_supplier_users_list() returns table(user_id uuid, username text, display_name text, email text, has_grant boolean, supplier text)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  return query
    select p.id, p.username, p.display_name, p.email,
           exists(select 1 from public.user_reports u where u.user_id = p.id and u.report_id = 'restock-supplier'),
           s.supplier
    from public.profiles p left join public.restock_supplier_users s on s.user_id = p.id
    where not p.disabled and not p.is_admin
    order by p.username;
end $$;

create function public.restock_supplier_user_set(p_user uuid, p_supplier text) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  if not exists (select 1 from public.profiles where id = p_user and not is_admin) then raise exception 'Unknown user'; end if;
  if p_supplier is null or btrim(p_supplier) = '' then
    delete from public.restock_supplier_users where user_id = p_user;
  else
    insert into public.restock_supplier_users(user_id, supplier) values (p_user, left(btrim(p_supplier), 100))
    on conflict (user_id) do update set supplier = excluded.supplier;
  end if;
end $$;

-- ---------- supplier ----------
create function public.restock_supplier_list() returns table(id text, product_id text, image text, variant_title text, qty integer, status text, added_at timestamptz, shipped_at timestamptz, supplier text)
language plpgsql stable security definer set search_path = '' as $$
declare s text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if s is null then raise exception 'Your account is not linked to a supplier yet. Ask Indifeels to link it.'; end if;
  return query
    select o.id, o.product_id, o.image, o.variant_title, o.qty, o.status, o.added_at, o.shipped_at, o.supplier
    from public.restock_orders o
    where o.supplier = s and (o.status <> 'shipped' or o.shipped_at > now() - interval '60 days')
    order by o.product_id, o.variant_title;
end $$;

create function public.restock_supplier_act(p_action text, p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text; n integer;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  if s is null then raise exception 'Your account is not linked to a supplier yet'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  if p_action = 'add' then
    update public.restock_orders set status = 'added', added_at = now(), updated_at = now()
      where supplier = s and id = any(p_ids) and status = 'saved';
  elsif p_action = 'unadd' then
    update public.restock_orders set status = 'saved', added_at = null, updated_at = now()
      where supplier = s and id = any(p_ids) and status = 'added';
  elsif p_action = 'ship' then
    update public.restock_orders set status = 'shipped', shipped_at = now(), updated_at = now()
      where supplier = s and id = any(p_ids) and status = 'added';
  else
    raise exception 'Bad action';
  end if;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.restock_owner_save(jsonb), public.restock_owner_received(text[]), public.restock_supplier_users_list(),
  public.restock_supplier_user_set(uuid, text), public.restock_supplier_list(), public.restock_supplier_act(text, text[]) from public, anon;
grant execute on function public.restock_owner_save(jsonb), public.restock_owner_received(text[]), public.restock_supplier_users_list(),
  public.restock_supplier_user_set(uuid, text), public.restock_supplier_list(), public.restock_supplier_act(text, text[]) to authenticated, service_role;

-- ---------- reports ----------
insert into public.reports(id, title, description, sort, category_id, admin_only) values
  ('restock-plan', 'Restock Planner', 'What to order, per variant, with supplier status', 28, 'stock', true),
  ('restock-supplier', 'Supplier Portal', 'Supplier view: items to restock, add to box, ship', 64, 'admin', false);

-- Schedule Panel: lets the planner be refreshed (and scheduled) from there like the other stock reports.
insert into public.report_refresh_control(report_id, enabled, runner) values ('restock-plan', true, 'restock-plan.yml')
  on conflict (report_id) do nothing;
