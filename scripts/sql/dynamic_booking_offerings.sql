-- Run against the existing booking database before deploying dynamic service creation.
-- Existing offerings keep their current calendar resource behavior.
begin;

alter table public.offerings add column if not exists archived boolean not null default false;
alter table public.offerings add column if not exists program_data jsonb not null default '{}'::jsonb;

create table if not exists public.camp_registrations (
    id uuid primary key,
    request_id uuid not null unique,
    offering_id uuid not null references public.offerings(id),
    session_label text not null,
    price_label text not null,
    amount_cents bigint not null check (amount_cents > 0),
    guardian_name text not null,
    guardian_email text not null,
    guardian_phone text not null,
    participant_name text not null,
    participant_grade text not null,
    waiver_confirmed boolean not null default false check (waiver_confirmed),
    status text not null default 'awaiting_payment' check (status in ('awaiting_payment', 'paid', 'payment_failed')),
    square_order_id text unique,
    square_payment_id text unique,
    payment_link_url text,
    created_at timestamptz not null default now()
);
alter table public.camp_registrations enable row level security;
revoke all on public.camp_registrations from public, anon, authenticated;
grant select, insert, update on public.camp_registrations to service_role;

create table if not exists public.booking_offering_resources (
    offering_id uuid not null references public.offerings(id) on delete cascade,
    resource text not null check (resource in ('field', 'backspace', 'party-area')),
    starts_after_minutes integer not null default 0 check (starts_after_minutes >= 0),
    ends_after_minutes integer check (ends_after_minutes is null or ends_after_minutes > starts_after_minutes),
    primary key (offering_id, resource)
);
alter table public.booking_offering_resources enable row level security;
revoke all on public.booking_offering_resources from public, anon, authenticated;
grant select, insert, update, delete on public.booking_offering_resources to service_role;

insert into public.booking_offering_resources (offering_id, resource, starts_after_minutes, ends_after_minutes)
select o.id, mapping.resource, mapping.starts_after_minutes, mapping.ends_after_minutes
from public.offerings o
cross join (values
    ('full-field', 'field', 0, null),
    ('speed-agility', 'backspace', 0, null),
    ('turf-fun-party', 'field', 0, 60),
    ('turf-fun-party', 'party-area', 60, null),
    ('ultimate-field-house-party', 'field', 0, 60),
    ('ultimate-field-house-party', 'party-area', 60, null)
) as mapping(slug, resource, starts_after_minutes, ends_after_minutes)
where o.slug = mapping.slug
on conflict (offering_id, resource) do nothing;

create or replace function public.booking_resources(p_slug text, p_start timestamptz)
returns table(resource text, during tstzrange)
language sql stable security definer set search_path = '' as $$
    select m.resource,
        tstzrange(
            p_start + make_interval(mins => m.starts_after_minutes),
            p_start + make_interval(mins => coalesce(m.ends_after_minutes, r.duration_minutes)),
            '[)'
        )
    from public.offerings o
    join public.booking_rules r on r.offering_id = o.id
    join public.booking_offering_resources m on m.offering_id = o.id
    where o.slug = p_slug and o.published and o.price_cents is not null;
$$;
revoke all on function public.booking_resources(text, timestamptz) from public, anon, authenticated;
grant execute on function public.booking_resources(text, timestamptz) to service_role;
commit;
