-- a supplier who picks an untagged product becomes that product's supplier from then on (first pick wins)
create table if not exists public.restock_product_tags(
  product_id text primary key, supplier text not null, tagged_at timestamptz not null default now(), synced_at timestamptz);
alter table public.restock_product_tags enable row level security;
revoke all on public.restock_product_tags from anon, authenticated;

create or replace function public.restock_blank_tag(t text) returns boolean
language sql immutable set search_path = '' as $$ select btrim(coalesce(t, '')) in ('', 'Unassigned') $$;

-- remember the supplier for untagged products picked now (inserted before the pick flips the lines to claimed)
create or replace function public.restock_supplier_pick(p_ids text[], p_box text default null, p_confirm boolean default false) returns text
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); c text; target text; sq integer; n integer; me text := public.restock_actor(); wp text[]; tagp text[];
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 500 then raise exception 'Bad request'; end if;
  c := public.restock_my_code();
  select array_agg(o.id) into wp from public.restock_orders o
    where o.id = any(p_ids) and o.status = 'saved' and not o.claimed and public.restock_tag_mismatch(o.supplier, idn);
  if wp is not null and not coalesce(p_confirm, false) then raise exception 'TAGGED_OTHER: % item(s) are tagged to another supplier', array_length(wp, 1); end if;
  select array_agg(distinct o.product_id) into tagp from public.restock_orders o
    where o.id = any(p_ids) and o.status = 'saved' and not o.claimed and public.restock_blank_tag(o.supplier) and o.product_id ~ '^[0-9]{1,20}$';
  if p_box is null then
    select box_no into target from public.restock_boxes where code = c and status = 'open' order by seq desc limit 1;
    if target is null then
      select coalesce(max(seq), 0) + 1 into sq from public.restock_boxes where code = c;
      target := 'Box-' || c || '-' || lpad(sq::text, 2, '0');
      insert into public.restock_boxes(box_no, code, seq, supplier) values (target, c, sq, idn);
    end if;
  else
    select box_no into target from public.restock_boxes where box_no = p_box and code = c and status = 'open';
    if target is null then raise exception 'That box is not available'; end if;
  end if;
  with u as (
    update public.restock_orders o set status = 'added', added_at = coalesce(o.added_at, now()), box_no = target, supplier = idn, claimed = true,
        orig_supplier = coalesce(o.orig_supplier, case when o.claimed then null else o.supplier end), added_by_name = me, updated_at = now()
    where o.id = any(p_ids) and (
        (o.status = 'saved' and not o.claimed)
        or (o.status = 'added' and (not o.claimed or o.supplier = idn)
            and (o.box_no is null or o.box_no in (select b.box_no from public.restock_boxes b where b.code = c and b.status = 'open'))))
    returning o.*),
  e as (insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
        select id, product_title || ' · ' || variant_title, supplier, me, 'supplier', 'boxed', coalesce(ship_qty, qty), target from u returning 1)
  select count(*) into n from u;
  if n = 0 then raise exception 'Nothing to add: those items are no longer on the master list'; end if;
  if wp is not null then
    with w as (update public.restock_orders set wrong_pick = true, wrong_ack = false where id = any(wp) and claimed and supplier = idn returning *)
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      select id, '⚠ WRONG PICK · ' || product_title || ' · ' || variant_title || ' (tagged to ' || coalesce(orig_supplier, '?') || ')', supplier, me, 'supplier', 'boxed', coalesce(ship_qty, qty), target from w;
  end if;
  if tagp is not null then
    insert into public.restock_product_tags(product_id, supplier) select unnest(tagp), idn on conflict (product_id) do nothing;
    -- other waiting lines of those products: tag them to the same supplier (unless another supplier owns the product)
    update public.restock_orders o set supplier = t.supplier, updated_at = now()
      from public.restock_product_tags t
      where t.product_id = o.product_id and o.product_id = any(tagp) and o.status = 'saved' and not o.claimed and public.restock_blank_tag(o.supplier);
  end if;
  return target;
end $$;

-- new order lines for a product already tagged this way carry the tag even before Shopify has it
create or replace function public.restock_owner_order(p jsonb) returns public.restock_orders
language plpgsql security definer set search_path = '' as $$
declare r public.restock_orders; vk text := p->>'vkey'; q integer := coalesce((p->>'qty')::integer, 0); me text := public.restock_actor(); sup text := left(coalesce(p->>'supplier',''), 100);
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if vk is null or length(vk) > 100 then raise exception 'Bad id'; end if;
  if q <= 0 or q > 100000 then raise exception 'Quantity must be at least 1'; end if;
  if public.restock_blank_tag(sup) then
    select t.supplier into sup from public.restock_product_tags t where t.product_id = left(coalesce(p->>'product_id',''), 30);
    sup := coalesce(sup, left(coalesce(p->>'supplier',''), 100));
  end if;
  insert into public.restock_orders(id, vkey, product_id, product_title, image, variant_title, supplier, qty, stock_base, saved_by, product_url)
  values (vk || '#' || nextval('public.restock_batch_seq'), vk, left(coalesce(p->>'product_id',''), 30), left(coalesce(p->>'product_title',''), 300),
          coalesce(nullif(p->>'image',''), ''), left(coalesce(p->>'variant_title',''), 120),
          sup, q, nullif(p->>'stock_base','')::integer, auth.uid(),
          case when length(p->>'product_url') <= 500 and p->>'product_url' ~* '^https://[^ ]+$' then p->>'product_url' end)
  returning * into r;
  insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to)
    values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'owner', 'ordered', r.qty);
  return r;
end $$;

create or replace function public.sync_get_restock_product_tags(p_token text) returns table(product_id text, supplier text, synced boolean)
language plpgsql security definer set search_path = '' as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select t.product_id, t.supplier, t.synced_at is not null from public.restock_product_tags t;
end $$;
create or replace function public.sync_mark_restock_product_tags(p_token text, p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare n integer;
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  update public.restock_product_tags set synced_at = now() where product_id = any(p_ids) and synced_at is null;
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.restock_blank_tag(text), public.sync_get_restock_product_tags(text), public.sync_mark_restock_product_tags(text, text[]) from public, anon, authenticated;
grant execute on function public.restock_blank_tag(text) to authenticated, service_role;
grant execute on function public.sync_get_restock_product_tags(text), public.sync_mark_restock_product_tags(text, text[]) to anon, authenticated, service_role;
