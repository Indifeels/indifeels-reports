-- Supplier declares a product permanently discontinued (double-confirmed on their screen); the owner then ticks a
-- confirmation, which marks it discontinued (same flag the planner's Discontinue button sets, synced to Shopify by the build)
-- and clears its unshipped lines from the master list and every open box.
create table if not exists public.restock_disc_requests(
  product_id text primary key check (product_id ~ '^[0-9]{1,20}$'),
  product_title text not null default '',
  image text not null default '',
  supplier text not null default '',
  requested_by_name text,
  requested_at timestamptz not null default now(),
  status text not null default 'pending' check (status in ('pending','approved','dismissed')),
  decided_by_name text,
  decided_at timestamptz
);
alter table public.restock_disc_requests enable row level security;
grant select on public.restock_disc_requests to authenticated;
grant all on public.restock_disc_requests to service_role;
create policy restock_disc_req_read on public.restock_disc_requests for select to authenticated using ((select public.can_view('restock-plan')));

create or replace function public.restock_supplier_discontinue(p_product text) returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); me text := public.restock_actor(); t text; i text; oid text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if p_product is null or p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  select o.id, o.product_title, o.image into oid, t, i from public.restock_orders o
    where o.product_id = p_product and (not o.claimed or o.supplier = idn) order by o.saved_at limit 1;
  if oid is null then raise exception 'Product not found on your lists'; end if;
  if exists (select 1 from public.restock_discontinued d where d.product_id = p_product and d.discontinued) then return 'done'; end if;
  insert into public.restock_disc_requests(product_id, product_title, image, supplier, requested_by_name)
  values (p_product, coalesce(t, ''), coalesce(i, ''), idn, me)
  on conflict (product_id) do update set status = 'pending', supplier = excluded.supplier, requested_by_name = excluded.requested_by_name,
    product_title = excluded.product_title, image = excluded.image, requested_at = now(), decided_by_name = null, decided_at = null
    where public.restock_disc_requests.status <> 'pending';
  return 'pending';
end $$;

create or replace function public.restock_supplier_disc_pending() returns text[]
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  return coalesce((select array_agg(r.product_id) from public.restock_disc_requests r where r.status = 'pending'), '{}');
end $$;

create or replace function public.restock_owner_disc_decide(p_product text, p_approve boolean) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer := 0; me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product is null or p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if p_approve then
    perform public.restock_owner_set_discontinued(p_product, true);
    with d as (delete from public.restock_orders where product_id = p_product and status in ('saved','added') returning *),
         e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_from, qty_to, box_no)
               select id, product_title || ' · ' || variant_title, supplier, me, 'owner', 'unordered', qty, 0, box_no from d returning 1)
    select count(*) into n from d;
  end if;
  update public.restock_disc_requests set status = case when p_approve then 'approved' else 'dismissed' end, decided_by_name = me, decided_at = now()
    where product_id = p_product and status = 'pending';
  return n;
end $$;

revoke all on function public.restock_supplier_discontinue(text), public.restock_supplier_disc_pending(), public.restock_owner_disc_decide(text, boolean) from public, anon, authenticated;
grant execute on function public.restock_supplier_discontinue(text), public.restock_supplier_disc_pending(), public.restock_owner_disc_decide(text, boolean) to authenticated, service_role;
