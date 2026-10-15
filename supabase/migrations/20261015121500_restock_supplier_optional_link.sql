-- Products are not tagged to suppliers yet: a Supplier Portal login that is not linked to a supplier name sees all items.
-- Linking a login to a supplier name (future) restricts it to that supplier's items again.
create or replace function public.restock_supplier_list() returns table(id text, product_id text, image text, variant_title text, qty integer, status text, added_at timestamptz, shipped_at timestamptz, supplier text)
language plpgsql stable security definer set search_path = '' as $$
declare s text;
begin
  if not public.can_view('restock-supplier') then raise exception 'Not allowed'; end if;
  select u.supplier into s from public.restock_supplier_users u where u.user_id = auth.uid();
  return query
    select o.id, o.product_id, o.image, o.variant_title, o.qty, o.status, o.added_at, o.shipped_at, o.supplier
    from public.restock_orders o
    where (s is null or o.supplier = s) and (o.status <> 'shipped' or o.shipped_at > now() - interval '60 days')
    order by o.product_id, o.variant_title;
end $$;

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
  elsif p_action = 'ship' then
    update public.restock_orders set status = 'shipped', shipped_at = now(), updated_at = now()
      where (s is null or supplier = s) and id = any(p_ids) and status = 'added';
  else
    raise exception 'Bad action';
  end if;
  get diagnostics n = row_count;
  return n;
end $$;
