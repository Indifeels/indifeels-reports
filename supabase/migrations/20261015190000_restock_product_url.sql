alter table public.restock_orders add column if not exists product_url text;

create or replace function public.restock_owner_order(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; vk text := p->>'vkey'; q integer := coalesce((p->>'qty')::integer, 0); me text := public.restock_actor();
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if vk is null or length(vk) > 100 then raise exception 'Bad id'; end if;
  if q <= 0 or q > 100000 then raise exception 'Quantity must be at least 1'; end if;
  insert into public.restock_orders(id, vkey, product_id, product_title, image, variant_title, supplier, qty, stock_base, saved_by, product_url)
  values (vk || '#' || nextval('public.restock_batch_seq'), vk, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          left(coalesce(p->>'supplier',''), 100), q, nullif(p->>'stock_base','')::integer, auth.uid(),
          case when p->>'product_url' ~* '^https://[^ ]{3,500}$' then p->>'product_url' end)
  returning * into r;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', r.qty);
  return r;
end $$;

create or replace function public.restock_supplier_state() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; act text; mx integer; orders jsonb; boxes jsonb;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  c := public.restock_my_code();
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
    where (not o.claimed or o.supplier = idn) and (o.status in ('saved','added') or o.shipped_at > now() - interval '90 days')) x;
  select coalesce(jsonb_agg(to_jsonb(b) order by b.seq desc), '[]'::jsonb) into boxes from (
    select box_no, seq, status, created_at, shipped_at, ship_date, tracking_url, tracking_no
    from public.restock_boxes where code = c and (status = 'open' or shipped_at > now() - interval '90 days')) b;
  return jsonb_build_object('identity', idn, 'code', c, 'active', act, 'orders', orders, 'boxes', boxes);
end $$;

-- supplier identity is case-insensitive in effect: 'pankaj' and 'Pankaj' are the same login (was producing codes P1 and P2)
create or replace function public.restock_box_identity() returns text
language sql stable security definer set search_path = '' as $$
  select initcap(btrim(coalesce((select u.supplier from public.restock_supplier_users u where u.user_id = auth.uid()), public.restock_actor(), 'X')))
$$;
