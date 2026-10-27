-- Under reported pieces: after the owner finishes a box, whatever did not arrive stays as a "Not received" row (status saved, short_box = box).
-- The supplier must ACCEPT it; only then it joins the normal order list (short_box cleared, unclaimed) and can be packed again.

alter table public.restock_events drop constraint if exists restock_events_action_check;
alter table public.restock_events add constraint restock_events_action_check
  check (action = any (array['ordered','unordered','boxed','unboxed','qty','shipped','received','notmine','short','accepted']));

create or replace function public.restock_supplier_accept_short(p_ids text[]) returns integer
language plpgsql security definer set search_path = '' as $$
declare idn text := public.restock_box_identity(); me text := public.restock_actor(); r record; n integer := 0;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  if coalesce(array_length(p_ids, 1), 0) = 0 or array_length(p_ids, 1) > 200 then raise exception 'Bad request'; end if;
  for r in select * from public.restock_orders where id = any(p_ids) and status = 'saved' and short_box is not null and supplier = idn for update loop
    update public.restock_orders set short_box = null, claimed = false, supplier = coalesce(r.orig_supplier, r.supplier), updated_at = now() where id = r.id;
    insert into public.restock_events(order_id, label, supplier, actor_name, actor_role, action, qty_to, box_no)
      values (r.id, r.product_title || ' · ' || r.variant_title, r.supplier, me, 'supplier', 'accepted', r.qty, r.short_box);
    n := n + 1;
  end loop;
  return n;
end $$;
revoke all on function public.restock_supplier_accept_short(text[]) from public, anon;
grant execute on function public.restock_supplier_accept_short(text[]) to authenticated, service_role;

-- Guard: an unaccepted under-reported row can't be packed into a box
create or replace function public.restock_block_unaccepted_short() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.status = 'added' and old.short_box is not null and new.short_box is not null then
    raise exception 'Accept the under reported items first';
  end if;
  return new;
end $$;
drop trigger if exists restock_block_unaccepted_short on public.restock_orders;
create trigger restock_block_unaccepted_short before update on public.restock_orders
  for each row when (old.status = 'saved' and new.status = 'added') execute function public.restock_block_unaccepted_short();
