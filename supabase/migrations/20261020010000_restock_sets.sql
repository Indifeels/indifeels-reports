-- explicit "full set" marker: set_n = number of full sets on a line (only lines created by Add full set); pill shows when every waiting line equals its set count
alter table public.restock_orders add column if not exists set_n integer not null default 0;
-- restock_owner_order(p) now reads p->>'set'; restock_supplier_state() now returns set_n (applied live; see git history of those functions)
