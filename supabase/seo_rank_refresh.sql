create or replace function public.publish_seo_rank_refresh(p_snapshot date,p_through date,p_rows jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare n integer;
begin
 if p_snapshot <> (now() at time zone 'Australia/Melbourne')::date or p_through>p_snapshot or p_through<p_snapshot-10 then raise exception 'Invalid or stale cutoff'; end if;
 if jsonb_typeof(p_rows)<>'array' or jsonb_array_length(p_rows)<>(select count(*) from public.seo_rank_products) then raise exception 'Incomplete product refresh'; end if;
 if exists(select 1 from public.seo_rank_categories where gsc_settled_through>p_through) then raise exception 'Data cutoff would regress'; end if;
 if exists(select 1 from public.seo_rank_categories where baseline_date>=p_snapshot) then raise exception 'Would replace baseline'; end if;
 if exists(select 1 from jsonb_to_recordset(p_rows) as x(category_id text,handle text,clicks integer,impressions integer) left join public.seo_rank_products p using(category_id,handle) where p.handle is null or x.clicks is null or x.impressions is null or x.clicks<0 or x.impressions<0) then raise exception 'Invalid product rows'; end if;
 if (select count(distinct (x->>'category_id',x->>'handle')) from jsonb_array_elements(p_rows) x)<>jsonb_array_length(p_rows) then raise exception 'Duplicate products'; end if;
 insert into public.seo_rank_snapshots(category_id,handle,snapshot_date,clicks,impressions,avg_position,target_position,target_impressions,top_query,top_query_position,top_query_impressions,indexed,coverage,last_crawl,top_queries)
 select x.category_id,x.handle,p_snapshot,x.clicks,x.impressions,x.avg_position,x.target_position,x.target_impressions,x.top_query,x.top_query_position,x.top_query_impressions,p.current_indexed,p.current_coverage,p.current_last_crawl,x.top_queries
 from jsonb_to_recordset(p_rows) as x(category_id text,handle text,clicks integer,impressions integer,avg_position numeric,target_position numeric,target_impressions integer,top_query text,top_query_position numeric,top_query_impressions integer,top_queries jsonb)
 join public.seo_rank_products p using(category_id,handle)
 on conflict(category_id,handle,snapshot_date) do update set clicks=excluded.clicks,impressions=excluded.impressions,avg_position=excluded.avg_position,target_position=excluded.target_position,target_impressions=excluded.target_impressions,top_query=excluded.top_query,top_query_position=excluded.top_query_position,top_query_impressions=excluded.top_query_impressions,top_queries=excluded.top_queries;
 get diagnostics n=row_count;
 update public.seo_rank_categories set refreshed_at=now(),gsc_settled_through=p_through where id in (select x->>'category_id' from jsonb_array_elements(p_rows) x);
 return jsonb_build_object('ok',true,'products',n,'snapshot_date',p_snapshot,'settled_through',p_through);
end;$$;
revoke all on function public.publish_seo_rank_refresh(date,date,jsonb) from public,anon,authenticated;
grant execute on function public.publish_seo_rank_refresh(date,date,jsonb) to service_role;
