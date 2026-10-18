-- Parked products (owner side only) + optional collection restriction per supplier login.

-- 1) Parked: products the owner can't restock right now. Hidden from the planner list unless the Parked filter is changed.
create table if not exists public.restock_parked(
  product_id text primary key, parked boolean not null default true,
  requested_by uuid, requested_by_name text, requested_at timestamptz not null default now());
alter table public.restock_parked enable row level security;
revoke all on public.restock_parked from anon, authenticated;
grant select on public.restock_parked to authenticated;
drop policy if exists restock_parked_read on public.restock_parked;
create policy restock_parked_read on public.restock_parked for select to authenticated using ((select public.can_view('restock-plan')));

create or replace function public.restock_owner_set_parked(p_product text, p_value boolean) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  insert into public.restock_parked(product_id, parked, requested_by, requested_by_name) values (p_product, p_value, auth.uid(), public.restock_actor())
  on conflict (product_id) do update set parked = excluded.parked, requested_by = auth.uid(), requested_by_name = excluded.requested_by_name, requested_at = now();
end $$;
revoke all on function public.restock_owner_set_parked(text, boolean) from public, anon;
grant execute on function public.restock_owner_set_parked(text, boolean) to authenticated;

-- 2) Supplier collection filter.
alter table public.restock_supplier_users add column if not exists collection text;

-- product -> collections, pushed by the Restock build (every run)
create table if not exists public.restock_product_cols(
  product_id text primary key, cols text[] not null default '{}', updated_at timestamptz not null default now());
alter table public.restock_product_cols enable row level security;
revoke all on public.restock_product_cols from anon, authenticated;

create or replace function public.sync_set_restock_product_cols(p_token text, p_rows jsonb) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  with r as (
    select (x->>'product_id') as product_id, coalesce(array(select jsonb_array_elements_text(x->'cols')), '{}') as cols
    from jsonb_array_elements(p_rows) x where (x->>'product_id') ~ '^[0-9]{1,20}$'),
  u as (
    insert into public.restock_product_cols(product_id, cols, updated_at) select product_id, cols, now() from r
    on conflict (product_id) do update set cols = excluded.cols, updated_at = now() returning 1)
  select count(*) into n from u;
  return n;
end $$;
revoke all on function public.sync_set_restock_product_cols(text, jsonb) from public, anon;
grant execute on function public.sync_set_restock_product_cols(text, jsonb) to anon, authenticated;

drop function if exists public.restock_supplier_user_set(uuid, text);
create or replace function public.restock_supplier_user_set(p_user uuid, p_supplier text, p_collection text default null) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  if not exists (select 1 from public.profiles where id = p_user and not is_admin) then raise exception 'Unknown user'; end if;
  if p_supplier is null or btrim(p_supplier) = '' then
    delete from public.restock_supplier_users where user_id = p_user;
  else
    insert into public.restock_supplier_users(user_id, supplier, collection) values (p_user, left(btrim(p_supplier), 100), nullif(left(btrim(coalesce(p_collection, '')), 100), ''))
    on conflict (user_id) do update set supplier = excluded.supplier, collection = excluded.collection;
  end if;
end $$;
revoke all on function public.restock_supplier_user_set(uuid, text, text) from public, anon;
grant execute on function public.restock_supplier_user_set(uuid, text, text) to authenticated;

drop function if exists public.restock_supplier_users_list();
create or replace function public.restock_supplier_users_list()
returns table(user_id uuid, username text, display_name text, email text, has_grant boolean, supplier text, collection text)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  return query
    select p.id, p.username, p.display_name, p.email,
           exists(select 1 from public.user_reports u where u.user_id = p.id and u.report_id = 'restock-supplier'),
           s.supplier, s.collection
    from public.profiles p left join public.restock_supplier_users s on s.user_id = p.id
    where not p.disabled and not p.is_admin
    order by p.username;
end $$;
revoke all on function public.restock_supplier_users_list() from public, anon;
grant execute on function public.restock_supplier_users_list() to authenticated;

-- supplier state: a login linked to a collection only sees waiting (unclaimed) items from products in that collection.
-- Lines the supplier already claimed / boxed stay visible. No collection set = sees everything, as before.
create or replace function public.restock_supplier_state() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; act text; mx integer; orders jsonb; boxes jsonb; mycol text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  select u.collection into mycol from public.restock_supplier_users u where u.user_id = auth.uid();
  select box_no into act from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if act is null then
    select coalesce(max(seq), 0) + 1 into mx from public.restock_boxes where code = c;
    act := 'Box-' || c || '-' || lpad(mx::text, 2, '0');
  end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.product_id, x.variant_title, x.saved_at), '[]'::jsonb) into orders from (
    select o.id, o.vkey, o.product_id, o.product_title, o.product_url, o.image, o.variant_title, o.qty, o.ship_qty, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.claimed,
           (not o.claimed and public.restock_tag_mismatch(o.supplier, idn)) as tagged_other,
           (not o.claimed and btrim(coalesce(o.supplier, '')) not in ('', 'Unassigned') and not public.restock_tag_mismatch(o.supplier, idn)) as tagged_mine
    from public.restock_orders o
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')
      and (mycol is null or o.claimed or exists (select 1 from public.restock_product_cols pc where pc.product_id = o.product_id and mycol = any(pc.cols)))) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $$;
