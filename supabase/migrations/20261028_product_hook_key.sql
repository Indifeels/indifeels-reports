create table if not exists public.product_hook_key (k text not null);
alter table public.product_hook_key enable row level security;
revoke all on public.product_hook_key from anon, authenticated;
