-- Owner can add / edit courier tracking (link + number) on any box from the Restock Planner (My view and Supplier view).
create or replace function public.restock_owner_tracking(p_box text, p_url text, p_no text) returns void
language plpgsql security definer set search_path = '' as $$
declare url text := nullif(btrim(coalesce(p_url, '')), ''); tno text := nullif(btrim(coalesce(p_no, '')), '');
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  if url is not null and (url !~ '^https?://' or length(url) > 500) then raise exception 'Tracking link must start with http:// or https://'; end if;
  if tno is not null and length(tno) > 80 then raise exception 'Tracking number is too long'; end if;
  update public.restock_boxes set tracking_url = url, tracking_no = tno where box_no = p_box;
  if not found then raise exception 'Unknown box'; end if;
end $$;
revoke all on function public.restock_owner_tracking(text, text, text) from public, anon;
grant execute on function public.restock_owner_tracking(text, text, text) to authenticated, service_role;
