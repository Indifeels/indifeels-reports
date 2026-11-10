-- export list lines now carry the product id, so the Excel export can fall back to the product's current photo
create or replace function public.restock_owner_export_list() returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.created_at desc) from (
    select e.code, e.supplier, e.status, e.units, e.created_at, e.created_by_name, jsonb_array_length(e.lines) as n,
           (select coalesce(jsonb_agg(l.v || jsonb_build_object('pid', o.product_id) order by l.ord), '[]'::jsonb)
              from jsonb_array_elements(e.lines) with ordinality as l(v, ord)
              left join public.restock_orders o on o.id = l.v->>'id') as lines
    from public.restock_exports e where e.status = 'sent' and e.created_at > now() - interval '120 days') x), '[]'::jsonb);
end $$;
