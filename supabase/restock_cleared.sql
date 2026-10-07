-- Restock "cleared" memory.
-- When a row is deleted or confirmed in the Restock report, its variant is stored here with the
-- report's data cut-off time. The next Restock build only counts sales made AFTER that time, so a
-- cleared item comes back only when it sells again, and only with the new sales.

create table if not exists public.restock_cleared (
  vid        text primary key,                       -- Shopify variant id (numeric part)
  cleared_at timestamptz not null,                   -- report data cut-off the user acted on
  reason     text not null default 'deleted',        -- 'deleted' | 'confirmed'
  cleared_by uuid,
  updated_at timestamptz not null default now()
);
alter table public.restock_cleared enable row level security;   -- no policies: only the functions below touch it

-- Called by the restock-confirm edge function (service role). Keeps the latest cut-off per variant.
create or replace function public.restock_mark_cleared(p_rows jsonb, p_user uuid, p_reason text)
returns integer
language plpgsql
security definer
set search_path to 'public'
as $$
declare n integer;
begin
  insert into public.restock_cleared (vid, cleared_at, reason, cleared_by)
  select r->>'vid', (r->>'asof')::timestamptz, p_reason, p_user
  from jsonb_array_elements(p_rows) r
  where (r->>'vid') ~ '^[0-9]{1,20}$'
  on conflict (vid) do update
    set cleared_at = greatest(public.restock_cleared.cleared_at, excluded.cleared_at),
        reason = excluded.reason,
        cleared_by = excluded.cleared_by,
        updated_at = now();
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.restock_mark_cleared(jsonb, uuid, text) from public, anon, authenticated;
grant execute on function public.restock_mark_cleared(jsonb, uuid, text) to service_role;

-- Called by the GitHub build with the existing read token.
create or replace function public.sync_get_restock_cleared(p_token text)
returns table(vid text, cleared_at timestamptz)
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not public.sync_check_token(p_token) then raise exception 'unauthorized'; end if;
  return query select c.vid, c.cleared_at from public.restock_cleared c;
end $$;
grant execute on function public.sync_get_restock_cleared(text) to anon, authenticated, service_role;
