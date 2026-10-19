-- A supplier login can be limited to several collections (was a single text column).
-- Empty / null = sees everything, as before.
alter table public.restock_supplier_users add column if not exists collections text[] not null default '{}';
update public.restock_supplier_users set collections = array[collection] where collection is not null and collections = '{}';

drop function if exists public.restock_supplier_user_set(uuid, text, text);
create or replace function public.restock_supplier_user_set(p_user uuid, p_supplier text, p_collections text[] default '{}') returns void
language plpgsql security definer set search_path = '' as $$
declare cols text[];
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  if not exists (select 1 from public.profiles where id = p_user and not is_admin) then raise exception 'Unknown user'; end if;
  select coalesce(array_agg(distinct left(btrim(c), 100)), '{}') into cols from unnest(coalesce(p_collections, '{}')) c where btrim(c) <> '';
  if p_supplier is null or btrim(p_supplier) = '' then
    delete from public.restock_supplier_users where user_id = p_user;
  else
    insert into public.restock_supplier_users(user_id, supplier, collection, collections) values (p_user, left(btrim(p_supplier), 100), null, cols)
    on conflict (user_id) do update set supplier = excluded.supplier, collection = null, collections = excluded.collections;
  end if;
end $$;
revoke all on function public.restock_supplier_user_set(uuid, text, text[]) from public, anon;
grant execute on function public.restock_supplier_user_set(uuid, text, text[]) to authenticated;

drop function if exists public.restock_supplier_users_list();
create or replace function public.restock_supplier_users_list()
returns table(user_id uuid, username text, display_name text, email text, has_grant boolean, supplier text, collections text[])
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_admin() then raise exception 'Not allowed'; end if;
  return query
    select p.id, p.username, p.display_name, p.email,
           exists(select 1 from public.user_reports u where u.user_id = p.id and u.report_id = 'restock-supplier'),
           s.supplier, coalesce(s.collections, '{}')
    from public.profiles p left join public.restock_supplier_users s on s.user_id = p.id
    where not p.disabled and not p.is_admin
    order by p.username;
end $$;
revoke all on function public.restock_supplier_users_list() from public, anon;
grant execute on function public.restock_supplier_users_list() to authenticated;

-- supplier state: a login with collections only sees waiting (unclaimed) items from products in ANY of its collections.
-- Lines the supplier already claimed / boxed stay visible. No collections = sees everything.
create or replace function public.restock_supplier_state() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; act text; mx integer; orders jsonb; boxes jsonb; mycols text[];
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
  select u.collections into mycols from public.restock_supplier_users u where u.user_id = auth.uid();
  if mycols is not null and cardinality(mycols) = 0 then mycols := null; end if;
  select box_no into act from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
  if act is null then
    select coalesce(max(seq), 0) + 1 into mx from public.restock_boxes where code = c;
    act := 'Box-' || c || '-' || lpad(mx::text, 2, '0');
  end if;
  select coalesce(jsonb_agg(to_jsonb(x) order by x.product_id, x.variant_title, x.saved_at), '[]'::jsonb) into orders from (
    select o.id, o.vkey, o.product_id, o.product_title, o.product_url, o.image, o.variant_title, o.qty, o.set_n, o.ship_qty, o.status, o.saved_at, o.added_at, o.shipped_at, o.box_no, o.ship_date, o.claimed,
           (not o.claimed and public.restock_tag_mismatch(o.supplier, idn)) as tagged_other,
           (not o.claimed and btrim(coalesce(o.supplier, '')) not in ('', 'Unassigned') and not public.restock_tag_mismatch(o.supplier, idn)) as tagged_mine
    from public.restock_orders o
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')
      and (mycols is null or o.claimed or exists (select 1 from public.restock_product_cols pc where pc.product_id = o.product_id and pc.cols && mycols))) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $$;
