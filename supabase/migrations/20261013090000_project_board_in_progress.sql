-- Project Board: add the In Progress column (col = 'progress'), between To Do and Roadblocks.
alter table public.board_tasks drop constraint board_tasks_col_check;
alter table public.board_tasks add constraint board_tasks_col_check check (col in ('backlog','todo','progress','stuck','done'));
