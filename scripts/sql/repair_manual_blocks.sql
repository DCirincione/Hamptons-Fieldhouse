-- Repairs the older manual-block setup on installations that only received the hours update.
-- Safe to rerun; existing bookings, hours, and blocks are preserved.
begin;
create table if not exists public.booking_block_series (
    id uuid primary key,
    title text not null check (length(trim(title)) between 1 and 200),
    request_payload jsonb not null,
    created_at timestamptz not null default now()
);
alter table public.booking_block_series enable row level security;
revoke all on public.booking_block_series from anon, authenticated;
alter table public.booking_resource_slots add column if not exists series_id uuid references public.booking_block_series(id);
create index if not exists booking_resource_slots_series_idx on public.booking_resource_slots(series_id);

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


create or replace function public.remove_schedule_block(p_id uuid,p_series boolean default false)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_slot public.booking_resource_slots; v_count integer;
begin
    select * into v_slot from public.booking_resource_slots where id = p_id for update;
    if not found then return jsonb_build_object('removed',0); end if;
    if v_slot.booking_id is not null then
        raise exception 'Use booking cancellation for customer bookings' using errcode = '22023';
    end if;
    if p_series and v_slot.series_id is not null then
        delete from public.booking_resource_slots where series_id = v_slot.series_id and booking_id is null;
    elsif v_slot.series_id is not null then
        -- Removing one occurrence releases all its selected spaces on that date/time.
        delete from public.booking_resource_slots where series_id = v_slot.series_id
            and during = v_slot.during and booking_id is null;
    else
        delete from public.booking_resource_slots where id = p_id;
    end if;
    get diagnostics v_count = row_count;
    return jsonb_build_object('removed',v_count);
end;
$$;
revoke all on function public.add_schedule_blocks(jsonb), public.remove_schedule_block(uuid,boolean) from public,anon,authenticated;
grant execute on function public.add_schedule_blocks(jsonb), public.remove_schedule_block(uuid,boolean) to service_role;
commit;
