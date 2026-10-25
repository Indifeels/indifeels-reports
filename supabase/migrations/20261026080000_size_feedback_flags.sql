alter table public.size_feedback
  add column if not exists flags text[],
  add column if not exists height_in numeric,
  add column if not exists base_size integer;
