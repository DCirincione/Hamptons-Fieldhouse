-- Run once against the existing booking database before deploying the hours editor.
-- Database deployment is managed separately from this repository.
begin;
create table public.booking_weekly_hours (
    weekday integer primary key check (weekday between 0 and 6), -- Monday = 0
    opens time,
    closes time,
    check ((opens is null and closes is null) or
           (opens is not null and closes is not null and opens < closes
            and closes < time '24:00' and extract(second from opens) = 0 and extract(second from closes) = 0))
);
insert into public.booking_weekly_hours select day, time '06:00', time '23:00' from generate_series(0,6) day;
create table public.booking_date_hours (
    date date primary key,
    opens time,
    closes time,
    check ((opens is null and closes is null) or
           (opens is not null and closes is not null and opens < closes
            and closes < time '24:00' and extract(second from opens) = 0 and extract(second from closes) = 0))
);
alter table public.booking_weekly_hours enable row level security;
alter table public.booking_date_hours enable row level security;
revoke all on public.booking_weekly_hours, public.booking_date_hours from public, anon, authenticated;

create function public.effective_opening_hours(p_date date)
returns table(opens time, closes time)
language sql stable security definer set search_path = '' as $$
    select case when d.date is not null then d.opens else w.opens end,
           case when d.date is not null then d.closes else w.closes end
    from public.booking_weekly_hours w
    left join public.booking_date_hours d on d.date = p_date
    where w.weekday = extract(isodow from p_date)::integer - 1;
$$;
create function public.staff_opening_hours()
returns jsonb language sql stable security definer set search_path = '' as $$
    select jsonb_build_object(
        'days', (select jsonb_agg(to_jsonb(w) order by weekday) from public.booking_weekly_hours w),
        'overrides', coalesce((select jsonb_agg(to_jsonb(d) order by date) from public.booking_date_hours d), '[]'::jsonb));
$$;
create function public.set_weekly_opening_hours(p_days jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
    if jsonb_typeof(p_days) is distinct from 'array' then
        raise exception 'Expected weekly hours' using errcode = '22023';
    end if;
    if jsonb_array_length(p_days) <> 7 or
       (select count(distinct (d->>'weekday')::integer) from jsonb_array_elements(p_days) d
        where (d->>'weekday')::integer between 0 and 6) <> 7 then
        raise exception 'Include every weekday once' using errcode = '22023';
    end if;
    -- Reservation creation already takes a shared lock on this row. Serialize
    -- hours changes against it, so bookings use either the old or new schedule.
    perform 1 from public.booking_policy where id for update;
    update public.booking_weekly_hours w set opens = (d->>'opens')::time, closes = (d->>'closes')::time
        from jsonb_array_elements(p_days) d where w.weekday = (d->>'weekday')::integer;
    return public.staff_opening_hours();
end;
$$;
create function public.set_date_opening_hours(p_day jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_date date := (p_day->>'date')::date;
    v_today date := (now() at time zone 'America/New_York')::date;
begin
    if v_date is null or v_date not between v_today and v_today + 365 then
        raise exception 'Choose a date within the next year' using errcode = '22023';
    end if;
    perform 1 from public.booking_policy where id for update;
    if coalesce((p_day->>'reset')::boolean, false) then
        delete from public.booking_date_hours where date = v_date;
    else
        insert into public.booking_date_hours (date,opens,closes)
        values (v_date,(p_day->>'opens')::time,(p_day->>'closes')::time)
        on conflict (date) do update set opens = excluded.opens, closes = excluded.closes;
    end if;
    return public.staff_opening_hours();
end;
$$;
revoke all on function public.effective_opening_hours(date), public.staff_opening_hours(),
    public.set_weekly_opening_hours(jsonb), public.set_date_opening_hours(jsonb) from public, anon, authenticated;
grant execute on function public.staff_opening_hours(), public.set_weekly_opening_hours(jsonb),
    public.set_date_opening_hours(jsonb) to service_role;

create or replace function public.booking_availability(p_slug text, p_month date)
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
    -- On-the-hour starts, entirely inside the effective hours for this date.
    select coalesce(jsonb_agg(jsonb_build_object('starts_at', s.starts_at, 'ends_at',
        s.starts_at + make_interval(mins => v_rule.duration_minutes)) order by s.starts_at), '[]'::jsonb)
    into v_slots
    from (
        select (d.day::date + make_time(h.hour, 0, 0)) at time zone 'America/New_York' as starts_at
        from generate_series(p_month::timestamp, (p_month + interval '1 month - 1 day')::timestamp, interval '1 day') d(day)
        cross join generate_series(0, 23) h(hour)
        cross join lateral public.effective_opening_hours(d.day::date) hours
        where d.day::date between v_today and v_today + v_policy.advance_days
        and hours.opens is not null
        and make_time(h.hour, 0, 0) >= hours.opens
        and h.hour * 60 + v_rule.duration_minutes <= extract(epoch from hours.closes) / 60
        -- Skip nonexistent local hours at the spring DST transition.
        and (((d.day::date + make_time(h.hour, 0, 0)) at time zone 'America/New_York')
             at time zone 'America/New_York') = d.day::date + make_time(h.hour, 0, 0)
    ) s
    where s.starts_at >= now() + make_interval(mins => v_policy.lead_minutes)
    and s.starts_at + make_interval(mins => v_rule.duration_minutes) <= (
        select ((s.starts_at at time zone 'America/New_York')::date + hours.closes) at time zone 'America/New_York'
        from public.effective_opening_hours((s.starts_at at time zone 'America/New_York')::date) hours
    )
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


create or replace function public.add_schedule_blocks(p_request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_id uuid := (p_request->>'request_id')::uuid;
    v_existing jsonb;
    v_slot jsonb;
    v_start timestamptz;
    v_end timestamptz;
    v_today date := (now() at time zone 'America/New_York')::date;
    v_resources text[];
begin
    if v_id is null or length(trim(coalesce(p_request->>'title',''))) not between 1 and 200
        or jsonb_typeof(p_request->'occurrences') is distinct from 'array'
        or jsonb_typeof(p_request->'resources') is distinct from 'array' then
        raise exception 'Invalid blocks' using errcode = '22023';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(v_id::text, 1));
    select request_payload into v_existing from public.booking_block_series where id = v_id;
    if found then
        if v_existing <> p_request then raise exception 'Request changed' using errcode = '22023'; end if;
        return jsonb_build_object('series_id', v_id, 'occurrences', jsonb_array_length(p_request->'occurrences'));
    end if;
    select array_agg(value) into v_resources from jsonb_array_elements_text(p_request->'resources');
    if coalesce(cardinality(v_resources),0) not between 1 and 3
        or not v_resources <@ array['field','backspace','party-area']::text[]
        or exists(select 1 from unnest(v_resources) r where r is null)
        or jsonb_array_length(p_request->'occurrences') not between 1 and 366 then
        raise exception 'Invalid blocks' using errcode = '22023';
    end if;
    insert into public.booking_block_series (id,title,request_payload)
        values (v_id,p_request->>'title',p_request);
    for v_slot in select value from jsonb_array_elements(p_request->'occurrences') loop
        v_start := (v_slot->>'starts_at')::timestamptz;
        v_end := (v_slot->>'ends_at')::timestamptz;
        if v_start is null or v_end is null or v_end <= v_start
           or (v_start at time zone 'America/New_York')::date <> (v_end at time zone 'America/New_York')::date
           or (v_start at time zone 'America/New_York')::date not between v_today and v_today + 365
           or date_trunc('minute',v_start) <> v_start or date_trunc('minute',v_end) <> v_end then
            raise exception 'Invalid time range' using errcode = '22023';
        end if;
        insert into public.booking_resource_slots (resource,during,note,series_id)
            select resource,tstzrange(v_start,v_end,'[)'),p_request->>'title',v_id
            from unnest(v_resources) resource;
    end loop;
    -- Any overlap raises 23P01 and rolls back the ENTIRE series, including its ID.
    return jsonb_build_object('series_id',v_id,'occurrences',jsonb_array_length(p_request->'occurrences'));
end;
$$;


commit;
