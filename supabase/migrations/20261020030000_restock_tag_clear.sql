-- Owner can remove a product's supplier: a blank supplier is stored as an override tag, the planner build then clears custom.supplier_name on Shopify.
create or replace function public.restock_owner_set_tag(p_product text, p_supplier text) returns integer
language plpgsql security definer set search_path = '' as $$
declare s text := btrim(coalesce(p_supplier, '')); n integer;
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if length(s) > 100 then raise exception 'Name too long'; end if;
  if public.restock_blank_tag(s) then
    insert into public.restock_product_tags(product_id, supplier, tagged_at, synced_at, override) values (p_product, '', now(), null, true)
      on conflict (product_id) do update set supplier = '', tagged_at = now(), synced_at = null, override = true;
    update public.restock_orders set supplier = 'Unassigned', updated_at = now()
      where product_id = p_product and status = 'saved' and not claimed and supplier is distinct from 'Unassigned';
  else
    insert into public.restock_product_tags(product_id, supplier, tagged_at, synced_at, override) values (p_product, s, now(), null, true)
      on conflict (product_id) do update set supplier = excluded.supplier, tagged_at = now(), synced_at = null, override = true;
    update public.restock_orders set supplier = s, updated_at = now()
      where product_id = p_product and status = 'saved' and not claimed and supplier is distinct from s;
  end if;
  get diagnostics n = row_count;
  return n;
end $$;
