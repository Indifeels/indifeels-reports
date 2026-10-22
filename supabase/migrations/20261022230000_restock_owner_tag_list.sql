-- owner can read supplier picks so the planner shows a new pick straight away (until the next build reflects it)
create or replace function public.restock_owner_tag_list() returns table(product_id text, supplier text, tagged_at timestamptz)
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return query select t.product_id, t.supplier, t.tagged_at from public.restock_product_tags t where t.override;
end $$;
revoke all on function public.restock_owner_tag_list() from public, anon;
grant execute on function public.restock_owner_tag_list() to authenticated, service_role;
