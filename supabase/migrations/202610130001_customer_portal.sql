-- Account-owned bookings, cash payment requests, and atomic repeating reservations.
begin;
alter table public.bookings add column customer_user_id uuid references auth.users(id) on delete set null;
create index bookings_customer_start_idx on public.bookings(customer_user_id, starts_at);
alter table public.bookings drop constraint bookings_payment_method_check;
alter table public.bookings add constraint bookings_payment_method_check check (payment_method in ('venmo','cash','other'));

-- Link existing bookings only to accounts whose email ownership is already verified.
update public.bookings b set customer_user_id = u.id
from auth.users u where u.email_confirmed_at is not null and lower(b.email) = lower(u.email);

create table public.customer_booking_requests (
    id uuid primary key,
    customer_user_id uuid not null references auth.users(id) on delete cascade,
    payload jsonb not null,
    created_at timestamptz not null default now()
);
alter table public.customer_booking_requests enable row level security;
revoke all on public.customer_booking_requests from anon, authenticated;
alter table public.bookings add column customer_request_id uuid references public.customer_booking_requests(id) on delete set null;
create index bookings_customer_request_idx on public.bookings(customer_request_id);

create or replace function public.reserve_booking(p_request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_id uuid := (p_request->>'request_id')::uuid;
    v_start timestamptz := (p_request->>'starts_at')::timestamptz;
    v_slug text := p_request->>'service';
    v_local timestamp;
    v_offer public.offerings;
    v_rule public.booking_rules;
    v_existing public.bookings;
    v_availability jsonb;
    v_count integer := (p_request->>'party_size')::integer;
    v_pizzas integer := coalesce((p_request->>'extra_pizzas')::integer, 0);
    v_food boolean := coalesce((p_request->>'own_food')::boolean, false);
    v_extra_children integer := 0;
    v_discount integer := 0;
    v_total integer;
    v_booking uuid;
begin
    if v_id is null or v_start is null or v_slug is null then
        raise exception 'Missing details' using errcode = '22023';
    end if;
    -- Same request key serializes retries and never creates a second reservation.
    perform pg_advisory_xact_lock(hashtextextended(v_id::text, 0));
    select * into v_existing from public.bookings where request_id = v_id;
    if found then
        if v_existing.request_payload <> p_request then
            raise exception 'Request changed' using errcode = '22023';
        end if;
        return jsonb_build_object('reference', v_existing.id, 'status', v_existing.status,
            'payment_status', v_existing.payment_status, 'total_price_cents', v_existing.total_price_cents,
            'starts_at', v_existing.starts_at, 'ends_at', v_existing.ends_at);
    end if;
    -- Stable catalog prices and policy for the whole transaction.
    perform 1 from public.booking_policy where id for share;
    select * into v_offer from public.offerings where slug = v_slug and published for share;
    select * into v_rule from public.booking_rules where offering_id = v_offer.id for share;
    perform 1 from public.booking_extras where slug in ('additional-child', 'pizza-with-toppings') for share;
    v_local := v_start at time zone 'America/New_York';
    v_availability := public.booking_availability(v_slug, date_trunc('month', v_local)::date);
    if not exists (select 1 from jsonb_array_elements(v_availability->'slots') s
                   where (s->>'starts_at')::timestamptz = v_start) then
        raise exception 'Time unavailable' using errcode = 'P0002';
    end if;
    if v_count is null or v_count not between 1 and 200 or v_pizzas not between 0 and 20
       or length(trim(coalesce(p_request->>'first_name', ''))) not between 1 and 100
       or length(trim(coalesce(p_request->>'last_name', ''))) not between 1 and 100
       or length(coalesce(p_request->>'email', '')) not between 3 and 254
       or length(coalesce(p_request->>'phone_number', '')) not between 7 and 30
       or length(coalesce(p_request->>'notes', '')) > 3000
       or coalesce(p_request->>'payment_method', '') not in ('venmo', 'cash', 'other') then
        raise exception 'Invalid details' using errcode = '22023';
    end if;
    v_total := v_offer.price_cents;
    if v_offer.category = 'birthday' then
        v_extra_children := greatest(0, v_count - v_offer.capacity);
        if (v_extra_children > 0 and v_availability->>'extra_child_cents' is null)
            or (v_pizzas > 0 and v_availability->>'extra_pizza_cents' is null)
            then
            raise exception 'Invalid extras' using errcode = '22023';
        end if;
        v_discount := case when v_food then v_rule.own_food_discount_cents else 0 end;
        v_total := v_total - v_discount
            + v_extra_children * coalesce((v_availability->>'extra_child_cents')::integer, 0)
            + v_pizzas * coalesce((v_availability->>'extra_pizza_cents')::integer, 0);
    elsif v_food or v_pizzas <> 0 then
        raise exception 'Party extras on rental' using errcode = '22023';
    end if;
    if (p_request->>'expected_total_cents')::integer is distinct from v_total then
        raise exception 'Price changed' using errcode = 'P0003';
    end if;
    insert into public.bookings (offering_id, first_name, last_name, email, phone_number,
        preferred_date, preferred_time, duration_minutes, party_size, notes, total_price_cents,
        starts_at, ends_at, request_id, request_payload, own_food, food_discount_cents, payment_method)
    values (v_offer.id, p_request->>'first_name', p_request->>'last_name', p_request->>'email', p_request->>'phone_number',
        v_local::date, v_local::time, v_rule.duration_minutes, v_count, coalesce(p_request->>'notes', ''), v_total,
        v_start, v_start + make_interval(mins => v_rule.duration_minutes), v_id, p_request, v_food, v_discount, p_request->>'payment_method')
    returning id into v_booking;
    -- Exclusion constraint also catches concurrent requests after availability was read.
    insert into public.booking_resource_slots (booking_id, resource, during)
        select v_booking, resource, during from public.booking_resources(v_slug, v_start);
    insert into public.booking_line_items (booking_id, extra_id, quantity, unit_price_cents)
        select v_booking, id, case slug when 'additional-child' then v_extra_children else v_pizzas end, unit_price_cents
        from public.booking_extras where published and
        ((slug = 'additional-child' and v_extra_children > 0) or (slug = 'pizza-with-toppings' and v_pizzas > 0));
    return jsonb_build_object('reference', v_booking, 'status', 'pending', 'payment_status', 'unpaid',
        'total_price_cents', v_total, 'starts_at', v_start,
        'ends_at', v_start + make_interval(mins => v_rule.duration_minutes));
end;
$$;


create function public.reserve_customer_bookings(p_user_id uuid, p_request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_email text;
    v_id uuid := (p_request->>'request_id')::uuid;
    v_previous public.customer_booking_requests;
    v_occurrence jsonb;
    v_result jsonb;
    v_booking uuid;
    v_method text := p_request->>'payment_method';
    v_results jsonb;
begin
    select email into v_email from auth.users where id = p_user_id and email_confirmed_at is not null;
    if v_email is null then raise exception 'Verified account required' using errcode = '42501'; end if;
    if v_id is null or jsonb_typeof(p_request->'occurrences') is distinct from 'array'
       or v_method is null or v_method not in ('venmo','cash','other') then
        raise exception 'Invalid request' using errcode = '22023';
    end if;
    if jsonb_array_length(p_request->'occurrences') not between 1 and 30 then
        raise exception 'Choose 1 to 30 occurrences' using errcode = '22023';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(v_id::text, 2));
    select * into v_previous from public.customer_booking_requests where id = v_id;
    if found then
        if v_previous.customer_user_id <> p_user_id or v_previous.payload <> p_request then
            raise exception 'Request changed' using errcode = '22023';
        end if;
    else
        insert into public.customer_booking_requests(id,customer_user_id,payload) values(v_id,p_user_id,p_request);
        for v_occurrence in select value from jsonb_array_elements(p_request->'occurrences') loop
            -- Occurrence keys must be new; only replay the outer, owner-checked request.
            if exists(select 1 from public.bookings where request_id = (v_occurrence->>'request_id')::uuid) then
                raise exception 'Request already used' using errcode = '22023';
            end if;
            v_result := public.reserve_booking((p_request - 'occurrences') || jsonb_build_object(
                'request_id', v_occurrence->>'request_id', 'starts_at', v_occurrence->>'starts_at', 'email',v_email));
            v_booking := (v_result->>'reference')::uuid;
            update public.bookings set customer_user_id=p_user_id, customer_request_id=v_id where id=v_booking;
        end loop;
    end if;
    -- A failure rolls back every occurrence. Replays reflect current approval status.
    select jsonb_agg(jsonb_build_object('reference',id,'status',status,'payment_status',payment_status,
        'total_price_cents',total_price_cents,'starts_at',starts_at,'ends_at',ends_at) order by starts_at)
    into v_results from public.bookings where customer_request_id=v_id and customer_user_id=p_user_id;
    return jsonb_build_object('request_id',v_id,'bookings',v_results,
        'occurrences',jsonb_array_length(v_results),
        'total_price_cents',(select sum(total_price_cents) from public.bookings where customer_request_id=v_id and customer_user_id=p_user_id));
end;
$$;

create function public.customer_bookings(p_user_id uuid, p_view text default 'upcoming', p_offset integer default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_rows jsonb; v_more boolean;
begin
    if not exists(select 1 from auth.users where id=p_user_id and email_confirmed_at is not null) then
        raise exception 'Verified account required' using errcode = '42501';
    end if;
    if p_view is null or p_view not in ('upcoming','history') or p_offset is null or p_offset < 0 then
        raise exception 'Invalid view' using errcode = '22023';
    end if;
    with owned as (
        select b.*,o.name from public.bookings b join public.offerings o on o.id=b.offering_id
        where b.customer_user_id=p_user_id and
        (case when p_view='upcoming' then b.ends_at >= now() and b.status <> 'cancelled'
              else b.ends_at < now() or b.status='cancelled' end)
        order by case when p_view='upcoming' then b.starts_at end asc,
                 case when p_view='history' then b.starts_at end desc, b.id
        offset p_offset limit 51
    ), numbered as (select *,row_number() over () as rn from owned)
    select coalesce(jsonb_agg(jsonb_build_object('id',n.id,'name',n.name,'starts_at',n.starts_at,'ends_at',n.ends_at,
        'status',n.status,'payment_status',n.payment_status,'payment_method',n.payment_method,
        'total_price_cents',n.total_price_cents,'party_size',n.party_size,'own_food',n.own_food,
        'request_id',n.customer_request_id,'recurring',
        (select count(*) > 1 from public.bookings siblings where siblings.customer_request_id=n.customer_request_id),
        'extras',coalesce((select jsonb_agg(jsonb_build_object('name',e.name,'quantity',li.quantity))
            from public.booking_line_items li join public.booking_extras e on e.id=li.extra_id where li.booking_id=n.id),'[]'::jsonb)
        ) order by n.rn) filter(where rn <= 50),'[]'::jsonb),count(*) > 50
    into v_rows,v_more from numbered n;
    return jsonb_build_object('bookings',v_rows,'has_more',v_more);
end;
$$;
revoke all on function public.reserve_customer_bookings(uuid,jsonb),public.customer_bookings(uuid,text,integer) from public,anon,authenticated;
grant execute on function public.reserve_customer_bookings(uuid,jsonb),public.customer_bookings(uuid,text,integer) to service_role;
commit;
