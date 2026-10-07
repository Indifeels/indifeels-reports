create table public.report_categories(id text primary key,title text not null,sort integer not null,color text not null default '#838099');
insert into public.report_categories values ('sales','Sales Analysis',1,'#568F8C'),('facebook','Facebook',2,'#986D7E'),('google','Google',3,'#AD915A'),('stock','Stock Management',4,'#708C74'),('seo','SEO',5,'#927CA2'),('admin','Admin Panel',6,'#838099');
alter table public.reports add column category_id text not null default 'admin' references public.report_categories(id), add column admin_only boolean not null default false;
update public.reports set category_id=case when id in ('order-source','order-attribution','call-tracking') then 'sales' when id in ('daily','monthly','facebook-tracked') then 'facebook' when id like 'google-%' then 'google' when id in ('stock','restock','product-visibility') then 'stock' when id='footwear' then 'seo' else 'admin' end;
insert into public.reports(id,title,description,sort,category_id,admin_only) values('report-access','Report Access','Manage people, admins and report permissions',61,'admin',true);
create table public.user_report_categories(user_id uuid references public.profiles(id) on delete cascade,category_id text references public.report_categories(id) on delete cascade,primary key(user_id,category_id));
alter table public.report_categories enable row level security;
alter table public.user_report_categories enable row level security;
grant select on public.report_categories,public.user_report_categories to authenticated;
grant all on public.report_categories,public.user_report_categories to service_role;
create policy categories_read on public.report_categories for select to authenticated using (true);
create policy category_grants_read on public.user_report_categories for select to authenticated using(user_id=(select auth.uid()) or (select public.is_admin()));
create or replace function public.can_view(rid text) returns boolean language sql stable security definer set search_path='' as $$
select exists(select 1 from public.profiles p join public.reports r on r.id=rid where p.id=auth.uid() and not p.disabled and (p.is_admin or (not r.admin_only and (exists(select 1 from public.user_reports u where u.user_id=p.id and u.report_id=r.id) or exists(select 1 from public.user_report_categories g where g.user_id=p.id and g.category_id=r.category_id)))));
$$;
revoke all on function public.can_view(text) from public,anon;
grant execute on function public.can_view(text) to authenticated,service_role;
create function public.save_user_report_access(target uuid,report_ids text[],category_ids text[]) returns void language plpgsql set search_path='' as $$
begin
if not exists(select 1 from public.profiles where id=target) then raise exception 'Unknown user'; end if;
if exists(select 1 from unnest(report_ids) x left join public.reports r on r.id=x where r.id is null or r.admin_only) then raise exception 'Invalid or admin-only report'; end if;
if exists(select 1 from unnest(category_ids) x left join public.report_categories c on c.id=x where c.id is null) then raise exception 'Unknown category'; end if;
delete from public.user_reports where user_id=target;
insert into public.user_reports(user_id,report_id) select target,x from (select distinct unnest(report_ids) x) q;
delete from public.user_report_categories where user_id=target;
insert into public.user_report_categories(user_id,category_id) select target,x from (select distinct unnest(category_ids) x) q;
end;
$$;
revoke all on function public.save_user_report_access(uuid,text[],text[]) from public,anon,authenticated;
grant execute on function public.save_user_report_access(uuid,text[],text[]) to service_role;
