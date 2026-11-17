-- Social Push List (for Davy): not-eligible products that only need a push, admin-only, under Command Centre.
insert into public.reports(id,title,description,sort,category_id,admin_only) values ('social-push','Social Push List','Products that need a push, not a discount: post these often, approve each post',1,'command',true) on conflict (id) do nothing;
insert into public.report_keys(report_id,key_b64) values ('social-push', encode(extensions.gen_random_bytes(32),'base64')) on conflict (report_id) do nothing;
