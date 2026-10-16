-- Restock Planner: admins keep default access; it is no longer admin-only, so an admin can grant it to individual people in Report Access.
update public.reports set admin_only=false where id='restock-plan';
