-- owner picks the supplier of an untagged product: same tag table the supplier pick uses, so the planner build pushes it to Shopify custom.supplier_name
create or replace function public.restock_owner_set_tag(p_product text, p_supplier text) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text := btrim(coalesce(p_supplier, '')); n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if public.restock_blank_tag(s) or length(s) > 100 then raise exception 'Pick a supplier'; end if;
  insert into public.restock_product_tags(product_id, supplier, tagged_at, synced_at) values (p_product, s, now(), null)
    on conflict (product_id) do update set supplier = excluded.supplier, tagged_at = now(), synced_at = null;
  update public.restock_orders set supplier = s, updated_at = now()
    where product_id = p_product and status = 'saved' and not claimed and public.restock_blank_tag(supplier);
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.restock_owner_set_tag(text, text) from public, anon;
grant execute on function public.restock_owner_set_tag(text, text) to authenticated, service_role;
