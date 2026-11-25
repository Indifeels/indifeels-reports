-- Barcode pick list: only lines that still have pieces to receive. Fully received boxes and PDF orders drop off.
create or replace function public.restock_owner_box_list()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.can_view('restock-plan') then raise exception 'Not allowed'; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) order by x.shipped_at desc nulls first, x.box_no, x.product_title, x.variant_title) from (
    select o.id, o.box_no, o.product_id, o.product_title, o.image, o.variant_title, o.supplier,
           coalesce(o.ship_qty, o.qty) as qty, o.recv_qty, o.status as line_status, o.hold_tag,
           coalesce(b.status, 'open') as box_status, b.shipped_at, b.ship_date, b.tracking_no
    from public.restock_orders o
    left join public.restock_boxes b on b.box_no = o.box_no
    where o.box_no is not null
      and o.status in ('added','shipped','on_the_way','received')
      and coalesce(o.recv_qty, 0) < coalesce(o.ship_qty, o.qty)
  ) x), '[]'::jsonb);
end $$;
