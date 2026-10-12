-- Indifeels Project Board: admin-only task board shown under Admin Panel.
-- Tasks are plain rows, so Claude, ChatGPT or any service-role script can insert/update them directly.
create table public.board_tasks(
  id uuid primary key default gen_random_uuid(),
  title text not null check (length(title) between 1 and 300),
  col text not null default 'backlog' check (col in ('backlog','todo','stuck','done')),
  pri text not null default 'none' check (pri in ('risk','none','low','med','urgent','done')),
  prev text check (prev is null or prev in ('risk','none','low','med','urgent')),
  pos double precision not null default (extract(epoch from clock_timestamp())*1000),
  source text not null default 'manual',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index board_tasks_col_pos on public.board_tasks(col,pos);

-- Keep colour and column consistent whoever writes the row: done <=> green.
create function public.board_tasks_normalise() returns trigger language plpgsql set search_path='' as $$
begin
  new.updated_at := now();
  if new.col='done' then
    if new.pri<>'done' then new.prev := new.pri; new.pri := 'done'; end if;
  elsif new.pri='done' then
    if tg_op='UPDATE' and old.col='done' then new.pri := coalesce(new.prev,'none');
    else new.col := 'done'; end if;
  end if;
  return new;
end;
$$;
create trigger board_tasks_normalise before insert or update on public.board_tasks
  for each row execute function public.board_tasks_normalise();

alter table public.board_tasks enable row level security;
create policy board_tasks_admin_all on public.board_tasks for all to authenticated
  using ((select public.is_admin())) with check ((select public.is_admin()));
grant select,insert,update,delete on public.board_tasks to authenticated;
grant all on public.board_tasks to service_role;

-- Registers the board in the hub (Admin Panel category, admins only). Run after the app code is deployed.
-- insert into public.reports(id,title,description,sort,category_id,admin_only)
-- values('project-board','Indifeels Project Board','Task board: Backlog, To Do, Roadblocks and Done, colour-coded by priority. Add tasks by telling Claude or ChatGPT.',62,'admin',true);
