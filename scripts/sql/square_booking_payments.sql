-- Apply in Supabase SQL Editor before enabling Square booking checkout.
-- Sandbox payments affect booking records: use test bookings while testing.
begin;
create table if not exists public.booking_square_payments (
  id uuid primary key,
  customer_user_id uuid not null references auth.users(id),
  booking_ids uuid[] not null,
  amount_cents bigint not null check (amount_cents > 0),
  location_id text not null,
  source_id text not null,
  status text not null default 'processing' check (status in ('processing','completed','failed')),
  square_payment_id text unique,
  created_at timestamptz not null default now()
);
alter table public.booking_square_payments enable row level security;
revoke all on public.booking_square_payments from public, anon, authenticated;
grant all on public.booking_square_payments to service_role;
create index if not exists booking_square_payments_owner on public.booking_square_payments(customer_user_id, status);
alter table public.bookings add column if not exists square_attempt_id uuid references public.booking_square_payments(id);
alter table public.bookings drop constraint if exists bookings_payment_method_check;
alter table public.bookings add constraint bookings_payment_method_check check (payment_method in ('venmo','cash','other','square'));

-- Lock dates in a stable order; a second tab/payment cannot charge overlapping dates.
drop function if exists public.begin_booking_square_payment(uuid,uuid,uuid[],text,text);
create or replace function public.begin_booking_square_payment(p_id uuid, p_user_id uuid, p_booking_ids uuid[], p_source text, p_location text, p_expected bigint)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_existing public.booking_square_payments; v_count int; v_amount bigint; v_ids uuid[];
begin
  select array_agg(distinct x order by x) into v_ids from unnest(p_booking_ids) x;
  if coalesce(cardinality(v_ids),0) < 1 or cardinality(v_ids) > 30 or cardinality(v_ids) <> cardinality(p_booking_ids) then
    raise exception 'Invalid dates' using errcode = '22023';
  end if;
  -- Serialize request-key reuse, even for different sets of dates.
  perform pg_advisory_xact_lock(hashtextextended(p_id::text, 0));
  select * into v_existing from public.booking_square_payments where id=p_id;
  if found then
    if v_existing.customer_user_id <> p_user_id or v_existing.booking_ids <> v_ids then
      raise exception 'Payment request mismatch' using errcode='22023';
    end if;
    return to_jsonb(v_existing);
  end if;
  perform id from public.bookings where id=any(v_ids) order by id for update;
  select count(*), sum(total_price_cents) into v_count,v_amount from public.bookings
    where id=any(v_ids) and customer_user_id=p_user_id and status in ('pending','confirmed')
    and payment_status='unpaid' and starts_at > now() and square_attempt_id is null;
  if v_count <> cardinality(v_ids) or v_amount <= 0 or v_amount <> p_expected then
    raise exception 'Dates are no longer payable or payment is already processing' using errcode='P0001';
  end if;
  insert into public.booking_square_payments(id,customer_user_id,booking_ids,amount_cents,source_id,location_id)
    values(p_id,p_user_id,v_ids,v_amount,p_source,p_location) returning * into v_existing;
  update public.bookings set square_attempt_id=p_id where id=any(v_ids);
  return to_jsonb(v_existing);
end $$;

-- Runs only with the server key after a verified Square response, never from browser claims.
create or replace function public.finish_booking_square_payment(p_id uuid, p_payment_id text, p_completed boolean)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_attempt public.booking_square_payments;
begin
  select * into v_attempt from public.booking_square_payments where id=p_id;
  if not found then raise exception 'Unknown payment' using errcode='22023'; end if;
  perform id from public.bookings where id=any(v_attempt.booking_ids) order by id for update;
  select * into v_attempt from public.booking_square_payments where id=p_id for update;
  if v_attempt.status <> 'processing' then return jsonb_build_object('status',v_attempt.status); end if;
  update public.booking_square_payments set status=case when p_completed then 'completed' else 'failed' end,
    square_payment_id=p_payment_id, source_id='' where id=p_id;
  if p_completed then
    update public.bookings set payment_status='paid', payment_method='square', status='confirmed'
      where id=any(v_attempt.booking_ids) and square_attempt_id=p_id;
  else
    update public.bookings set square_attempt_id=null where id=any(v_attempt.booking_ids) and square_attempt_id=p_id;
  end if;
  return jsonb_build_object('status',case when p_completed then 'completed' else 'failed' end);
end $$;

create or replace function public.guard_booking_square_payment()
returns trigger language plpgsql security definer set search_path=public as $$
begin
  if old.square_attempt_id is not null and exists (
    select 1 from public.booking_square_payments where id=old.square_attempt_id and status='processing'
  ) and (new.status='cancelled' or new.total_price_cents is distinct from old.total_price_cents
         or new.starts_at is distinct from old.starts_at or new.ends_at is distinct from old.ends_at
         or new.payment_status is distinct from old.payment_status
         or new.square_attempt_id is distinct from old.square_attempt_id) then
    raise exception 'Square payment is processing. Check payment status before changing this booking.' using errcode='P0001';
  end if;
  return new;
end $$;
drop trigger if exists guard_booking_square_payment on public.bookings;
create trigger guard_booking_square_payment before update on public.bookings
  for each row execute function public.guard_booking_square_payment();
revoke all on function public.begin_booking_square_payment(uuid,uuid,uuid[],text,text,bigint) from public,anon,authenticated;
revoke all on function public.finish_booking_square_payment(uuid,text,boolean) from public,anon,authenticated;
revoke all on function public.guard_booking_square_payment() from public,anon,authenticated;
grant execute on function public.begin_booking_square_payment(uuid,uuid,uuid[],text,text,bigint) to service_role;
grant execute on function public.finish_booking_square_payment(uuid,text,boolean) to service_role;
commit;
