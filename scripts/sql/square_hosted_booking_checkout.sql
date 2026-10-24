-- Apply after square_booking_payments.sql to add Square-hosted booking checkout.
begin;
alter table public.booking_square_payments add column if not exists square_order_id text unique;
alter table public.booking_square_payments add column if not exists payment_link_url text;

create or replace function public.attach_booking_square_link(p_id uuid, p_order_id text, p_url text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_attempt public.booking_square_payments;
begin
  select * into v_attempt from public.booking_square_payments where id=p_id for update;
  if not found or v_attempt.status <> 'processing' then
    raise exception 'Unknown or completed payment' using errcode='22023';
  end if;
  if v_attempt.square_order_id is not null and (v_attempt.square_order_id <> p_order_id or v_attempt.payment_link_url <> p_url) then
    raise exception 'Payment link mismatch' using errcode='22023';
  end if;
  update public.booking_square_payments set square_order_id=p_order_id, payment_link_url=p_url
    where id=p_id returning * into v_attempt;
  return to_jsonb(v_attempt);
end $$;

revoke all on function public.attach_booking_square_link(uuid,text,text) from public,anon,authenticated;
grant execute on function public.attach_booking_square_link(uuid,text,text) to service_role;
commit;
