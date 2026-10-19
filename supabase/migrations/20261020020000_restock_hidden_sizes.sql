-- Sizes the owner no longer stocks: hidden from the Restock Planner list (app only, nothing changes in Shopify).
-- Same pattern as restock_parked. Bring a size back with "Add size" (the planner un-hides it).
create table if not exists public.restock_hidden_sizes(
  vkey text primary key, product_id text not null, variant_title text not null,
  hidden_by uuid, hidden_at timestamptz not null default now());
alter table public.restock_hidden_sizes enable row level security;
revoke all on public.restock_hidden_sizes from anon, authenticated;
grant select on public.restock_hidden_sizes to authenticated;
drop policy if exists restock_hidden_sizes_read on public.restock_hidden_sizes;
create policy restock_hidden_sizes_read on public.restock_hidden_sizes for select to authenticated using ((select public.can_view('restock-plan')));

create or replace function public.restock_owner_set_size_hidden(p_vkey text, p_product text, p_title text, p_hidden boolean) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if p_product !~ '^[0-9]{1,20}$' then raise exception 'Bad product'; end if;
  if p_vkey is null or length(p_vkey) > 100 or p_vkey <> p_product || '|' || p_title then raise exception 'Bad size'; end if;
  if p_hidden then
    insert into public.restock_hidden_sizes(vkey, product_id, variant_title, hidden_by) values (p_vkey, p_product, left(p_title, 120), auth.uid())
    on conflict (vkey) do nothing;
  else
    delete from public.restock_hidden_sizes where vkey = p_vkey;
  end if;
end $$;
revoke all on function public.restock_owner_set_size_hidden(text, text, text, boolean) from public, anon;
grant execute on function public.restock_owner_set_size_hidden(text, text, text, boolean) to authenticated;
