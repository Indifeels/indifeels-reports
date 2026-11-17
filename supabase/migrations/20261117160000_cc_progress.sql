create table if not exists public.cc_progress(
  id text primary key, phase text not null, title text not null,
  pct int not null default 0 check (pct between 0 and 100),
  status text not null default 'next' check (status in ('done','doing','next','blocked')),
  note text not null default '', sort int not null default 0, updated_at timestamptz not null default now());
alter table public.cc_progress enable row level security;
create policy cc_progress_admin on public.cc_progress for all to authenticated using ((select public.is_admin())) with check ((select public.is_admin()));
grant select, insert, update, delete on public.cc_progress to authenticated;
grant all on public.cc_progress to service_role;
insert into public.cc_progress(id,phase,title,pct,status,note,sort) values
('a1','Foundation','Command Centre front page, tiles, map',100,'done','',1),
('a2','Foundation','Published in the reports hub, admin only',100,'done','',2),
('a3','Foundation','Missions, XP and voice answers',100,'done','',3),
('a4','Foundation','Answers saved to your account',100,'done','',4),
('a5','Foundation','Knowledge base and 10 agent playbooks',80,'doing','Your 31 answers are in. A few TO CONFIRM items still open.',5),
('a6','Foundation','Live project progress (this page)',90,'doing','Updates as work happens.',6),
('b1','Profit first','Clearance tiers in Profit Flow',80,'doing','Tiers are live. You approve each price.',10),
('b2','Profit first','Social Push List for Davy',60,'doing','List is live. Auto-posting is not built yet.',11),
('b3','Profit first','Stock gaps on sellers, by variant',25,'doing','By product: 34 sold out, 9 low. Variant list next.',12),
('b4','Profit first','Check Google Purchase conversion against Shopify',0,'next','',13),
('b5','Profit first','Meta Pixel purchase test',0,'next','',14),
('b6','Profit first','Offline conversion import (calls, store visits)',0,'next','',15),
('b7','Profit first','Exact Tarneit and Blacktown dates from Shopify',0,'next','',16),
('b8','Profit first','Competitor websites (8 names)',0,'next','',17),
('c1','Intelligence','Real performance score on each tile',10,'doing','Knowledge % only so far. Real numbers next.',20),
('c2','Intelligence','Decisions Inbox: bots suggest, you approve',0,'next','',21),
('c3','Intelligence','Strategy Tracker',0,'next','',22),
('c4','Intelligence','Automation Board',0,'next','',23),
('c5','Intelligence','Reports open on the same screen',0,'next','',24),
('c6','Intelligence','Semrush scheduled emails',0,'blocked','Waiting for you to schedule them.',25),
('c7','Intelligence','Bots plan test campaigns ($5 to $15 a day, you approve)',0,'next','',26)
on conflict (id) do nothing;
