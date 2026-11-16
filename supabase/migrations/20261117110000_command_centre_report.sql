-- Master Dashboard (Command Centre): new top section, admin-only report, encryption key generated in the database.
insert into public.report_categories(id,title,sort,color) values ('command','Command Centre',-1,'#2BB5A5') on conflict (id) do nothing;
insert into public.reports(id,title,description,sort,category_id,admin_only) values ('command-centre','Master Dashboard','Business map: scored areas, alerts, drill-down tiles and how they connect',0,'command',true) on conflict (id) do nothing;
insert into public.report_keys(report_id,key_b64) values ('command-centre', encode(extensions.gen_random_bytes(32),'base64')) on conflict (report_id) do nothing;
