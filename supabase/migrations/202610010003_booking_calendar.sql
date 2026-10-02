-- Apply after the catalog migrations. No payment is collected by this flow.
begin;
create extension if not exists btree_gist with schema extensions;
set local search_path = public, extensions;

create table public.booking_policy (
    id boolean primary key default true check (id),
    enabled boolean not null default false,
    independent_spaces boolean not null default true,
    party_field_minutes integer not null default 60 check (party_field_minutes in (60, 90)),
    advance_days integer not null default 90 check (advance_days between 1 and 365),
    lead_minutes integer not null default 60 check (lead_minutes between 0 and 10080)
);
insert into public.booking_policy (id) values (true);

create table public.booking_rules (
    offering_id uuid primary key references public.offerings(id),
    resource text not null check (resource in ('field', 'backspace')),
    duration_minutes integer not null check (duration_minutes in (60, 90)),
    own_food_discount_cents integer not null default 0 check (own_food_discount_cents >= 0)
);
insert into public.booking_rules (offering_id, resource, duration_minutes, own_food_discount_cents)
select id, case when slug = 'speed-agility' then 'backspace' else 'field' end,
       case when category = 'birthday' then 90 else 60 end,
       case slug when 'turf-fun-party' then 5000 when 'ultimate-field-house-party' then 6000 else 0 end
from public.offerings where slug in ('full-field', 'speed-agility', 'turf-fun-party', 'ultimate-field-house-party');

alter table public.bookings drop constraint bookings_status_check;
alter table public.bookings add constraint bookings_status_check check (status in ('pending', 'confirmed', 'cancelled'));
alter table public.bookings alter column status set default 'pending';

alter table public.bookings
    add column payment_method text not null default 'other' check (payment_method in ('venmo', 'other')),
    add column starts_at timestamptz,
    add column ends_at timestamptz,
    add column request_id uuid unique,
    add column request_payload jsonb,
    add column own_food boolean not null default false,
    add column food_discount_cents integer not null default 0,
    add column payment_status text not null default 'unpaid' check (payment_status in ('unpaid', 'paid', 'refunded'));

-- Preserve existing reservations when moving from the old date/time columns.
update public.bookings set
    starts_at = (preferred_date + preferred_time) at time zone 'America/New_York',
    ends_at = ((preferred_date + preferred_time) at time zone 'America/New_York') + make_interval(mins => duration_minutes);
alter table public.bookings alter column starts_at set not null;
alter table public.bookings alter column ends_at set not null;
alter table public.bookings add constraint booking_positive_interval check (ends_at > starts_at);

-- Rows without a booking_id are staff-entered closures/maintenance blocks.
create table public.booking_resource_slots (
    id uuid primary key default gen_random_uuid(),
    booking_id uuid references public.bookings(id),
    resource text not null check (resource in ('field', 'backspace', 'party-area')),
    during tstzrange not null check (not isempty(during) and not lower_inf(during) and not upper_inf(during)),
    note text not null default '',
    exclude using gist (resource with =, during with &&)
);

alter table public.booking_policy enable row level security;
alter table public.booking_rules enable row level security;
alter table public.booking_resource_slots enable row level security;
revoke all on public.booking_policy, public.booking_rules, public.booking_resource_slots from anon, authenticated;

-- One shared function defines resource use for both browsing and reservation.
create function public.booking_resources(p_slug text, p_start timestamptz)
returns table(resource text, during tstzrange)
language sql stable security definer set search_path = '' as $$
    select r.resource, tstzrange(p_start, p_start + make_interval(mins =>
        case when o.category = 'birthday' then p.party_field_minutes else r.duration_minutes end), '[)')
    from public.booking_rules r join public.offerings o on o.id = r.offering_id
    cross join public.booking_policy p where o.slug = p_slug
    union all
    select case r.resource when 'field' then 'backspace' else 'field' end,
        tstzrange(p_start, p_start + make_interval(mins =>
        case when o.category = 'birthday' then p.party_field_minutes else r.duration_minutes end), '[)')
    from public.booking_rules r join public.offerings o on o.id = r.offering_id
    cross join public.booking_policy p where o.slug = p_slug and not p.independent_spaces
    union all
    select 'party-area', tstzrange(
        p_start + make_interval(mins => case when p.party_field_minutes = 60 then 60 else 0 end),
        p_start + interval '90 minutes', '[)')
    from public.offerings o cross join public.booking_policy p
    where o.slug = p_slug and o.category = 'birthday';
$$;

-- Migrate active legacy rentals conservatively; fail if existing records overlap
-- so staff must reconcile them before enabling the calendar.
insert into public.booking_resource_slots (booking_id, resource, during)
select b.id, r.resource, tstzrange(b.starts_at, b.ends_at, '[)')
from public.bookings b join public.offerings o on o.id = b.offering_id
cross join lateral public.booking_resources(o.slug, b.starts_at) r
where b.status <> 'cancelled';
-- Unknown legacy offerings (including half-field) block both rental spaces.
insert into public.booking_resource_slots (booking_id, resource, during)
select b.id, resource, tstzrange(b.starts_at, b.ends_at, '[)')
from public.bookings b cross join (values ('field'), ('backspace')) resources(resource)
where b.status <> 'cancelled' and not exists (
    select 1 from public.booking_rules where offering_id = b.offering_id
);

create function public.booking_availability(p_slug text, p_month date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
    v_offer public.offerings;
    v_rule public.booking_rules;
    v_policy public.booking_policy;
    v_slots jsonb;
    v_today date := (now() at time zone 'America/New_York')::date;
    v_child integer;
    v_pizza integer;
begin
    select * into v_policy from public.booking_policy where id;
    if not v_policy.enabled then raise exception 'Booking unavailable' using errcode = '55000'; end if;
    if p_month is null or p_month <> date_trunc('month', p_month)::date
       or p_month < date_trunc('month', v_today)::date
       or p_month > v_today + v_policy.advance_days then
        raise exception 'Invalid month' using errcode = '22023';
    end if;
    select * into v_offer from public.offerings where slug = p_slug and published and price_cents is not null;
    select * into v_rule from public.booking_rules where offering_id = v_offer.id;
    if v_rule.offering_id is null then raise exception 'Service unavailable' using errcode = '22023'; end if;
    select unit_price_cents into v_child from public.booking_extras where slug = 'additional-child' and published;
    select unit_price_cents into v_pizza from public.booking_extras where slug = 'pizza-with-toppings' and published;
    -- On-the-hour starts. A 90-minute party must end by 11 PM (last start 9 PM).
    select coalesce(jsonb_agg(jsonb_build_object('starts_at', s.starts_at, 'ends_at',
        s.starts_at + make_interval(mins => v_rule.duration_minutes)) order by s.starts_at), '[]'::jsonb)
    into v_slots
    from (
        select (d.day::date + make_time(h.hour, 0, 0)) at time zone 'America/New_York' as starts_at
        from generate_series(p_month::timestamp, (p_month + interval '1 month - 1 day')::timestamp, interval '1 day') d(day)
        cross join generate_series(6, 22) h(hour)
        where d.day::date between v_today and v_today + v_policy.advance_days
        and h.hour * 60 + v_rule.duration_minutes <= 23 * 60
    ) s
    where s.starts_at >= now() + make_interval(mins => v_policy.lead_minutes)
    and not exists (
        select 1 from public.booking_resources(p_slug, s.starts_at) wanted
        join public.booking_resource_slots busy on busy.resource = wanted.resource and busy.during && wanted.during
    );
    return jsonb_build_object('service', p_slug, 'name', v_offer.name,
        'category', v_offer.category, 'price_cents', v_offer.price_cents,
        'duration_minutes', v_rule.duration_minutes, 'included_children', v_offer.capacity,
        'own_food_discount_cents', v_rule.own_food_discount_cents,
        'extra_child_cents', v_child, 'extra_pizza_cents', v_pizza,
        'timezone', 'America/New_York', 'today', v_today,
        'last_date', v_today + v_policy.advance_days, 'slots', v_slots);
end;
$$;

create function public.reserve_booking(p_request jsonb)
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
       or coalesce(p_request->>'payment_method', '') not in ('venmo', 'other') then
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

-- Staff cancellation releases all occupied spaces atomically. Rebooking is required
-- to reinstate a cancelled reservation; direct edits cannot silently bypass conflicts.
create function public.booking_status_changed() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
    if old.status = 'cancelled' and new.status <> 'cancelled' then
        raise exception 'Create a new reservation to rebook';
    end if;
    if new.status = 'cancelled' then
        delete from public.booking_resource_slots where booking_id = new.id;
    end if;
    if (new.starts_at, new.ends_at, new.offering_id) is distinct from (old.starts_at, old.ends_at, old.offering_id) then
        raise exception 'Cancel and rebook to change a reservation';
    end if;
    return new;
end;
$$;
create trigger booking_status_changed before update on public.bookings
    for each row execute function public.booking_status_changed();

revoke all on function public.booking_resources(text, timestamptz) from public, anon, authenticated;
revoke all on function public.booking_availability(text, date) from public, anon, authenticated;
revoke all on function public.reserve_booking(jsonb) from public, anon, authenticated;
revoke all on function public.booking_status_changed() from public, anon, authenticated;
grant execute on function public.booking_availability(text, date), public.reserve_booking(jsonb) to service_role;

create table public.booking_staff_actions (
    id uuid primary key default gen_random_uuid(),
    booking_id uuid not null references public.bookings(id),
    action text not null check (action in ('approve', 'cancel')),
    created_at timestamptz not null default now()
);
alter table public.booking_staff_actions enable row level security;
revoke all on public.booking_staff_actions from anon, authenticated;

create function public.review_booking(p_id uuid, p_action text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_booking public.bookings;
begin
    if p_action not in ('approve', 'cancel') or p_action is null then
        raise exception 'Invalid action' using errcode = '22023';
    end if;
    select * into v_booking from public.bookings where id = p_id for update;
    if not found then raise exception 'Missing booking' using errcode = '22023'; end if;
    if (p_action = 'approve' and v_booking.status = 'confirmed') or
       (p_action = 'cancel' and v_booking.status = 'cancelled') then
        return jsonb_build_object('status', v_booking.status);
    end if;
    if v_booking.status = 'cancelled' then raise exception 'Already cancelled' using errcode = '22023'; end if;
    update public.bookings set status = case p_action when 'approve' then 'confirmed' else 'cancelled' end
        where id = p_id;
    insert into public.booking_staff_actions (booking_id, action) values (p_id, p_action);
    return jsonb_build_object('status', case p_action when 'approve' then 'confirmed' else 'cancelled' end);
end;
$$;
revoke all on function public.review_booking(uuid, text) from public, anon, authenticated;
grant execute on function public.review_booking(uuid, text) to service_role;
grant select on public.bookings, public.offerings, public.booking_line_items, public.booking_extras to service_role;
commit;
