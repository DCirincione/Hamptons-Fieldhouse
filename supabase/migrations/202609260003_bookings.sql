-- Run in Supabase SQL Editor after reviewing. This adds tables without changing
-- contact_messages. Public booking writes are disabled until atomic confirmation
-- and resource-overlap rules are implemented.
begin;

create table public.offerings (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    category text not null check (category in ('field_rental', 'camp', 'clinic', 'birthday', 'event')),
    name text not null check (length(name) between 1 and 120),
    description text not null default '',
    details jsonb not null default '[]'::jsonb check (jsonb_typeof(details) = 'array'),
    price_cents integer check (price_cents >= 0),
    duration_minutes integer check (duration_minutes > 0),
    capacity integer check (capacity > 0),
    published boolean not null default false,
    sort_order integer not null default 0,
    created_at timestamptz not null default now()
);

create table public.program_sessions (
    id uuid primary key default gen_random_uuid(),
    offering_id uuid not null references public.offerings(id),
    starts_at timestamptz not null,
    ends_at timestamptz not null check (ends_at > starts_at),
    capacity integer check (capacity > 0),
    published boolean not null default false,
    created_at timestamptz not null default now()
);

create table public.bookings (
    id uuid primary key default gen_random_uuid(),
    offering_id uuid not null references public.offerings(id),
    session_id uuid references public.program_sessions(id),
    first_name text not null check (length(trim(first_name)) between 1 and 100),
    last_name text not null check (length(trim(last_name)) between 1 and 100),
    email text not null check (length(email) between 3 and 254),
    phone_number text not null check (length(phone_number) between 7 and 30),
    preferred_date date not null,
    preferred_time time not null,
    duration_minutes integer not null check (duration_minutes between 30 and 480),
    party_size integer not null check (party_size between 1 and 200),
    notes text not null default '' check (length(notes) <= 3000),
    status text not null default 'confirmed'
        check (status in ('confirmed', 'cancelled')),
    total_price_cents integer check (total_price_cents >= 0),
    created_at timestamptz not null default now()
);

create index bookings_created_at_idx on public.bookings(created_at desc);
create index bookings_offering_idx on public.bookings(offering_id);
create index program_sessions_offering_idx on public.program_sessions(offering_id);

alter table public.offerings enable row level security;
alter table public.program_sessions enable row level security;
alter table public.bookings enable row level security;

revoke all on public.offerings, public.program_sessions, public.bookings from anon, authenticated;
grant select on public.offerings, public.program_sessions to anon, authenticated;
create policy "Read published offerings" on public.offerings
    for select to anon, authenticated using (published);
create policy "Read published program sessions" on public.program_sessions
    for select to anon, authenticated using (
        published and exists (select 1 from public.offerings o where o.id = offering_id and o.published)
    );
insert into public.offerings (slug, category, name, description, details, price_cents, duration_minutes, capacity, published, sort_order) values
('full-field', 'field_rental', 'Full Field', 'Room for your whole team to practice, play, and compete.', '["Full turf field", "Daily rental hours: 6 AM\u201311 PM"]'::jsonb, null, null, null, true, 10),
('half-field', 'field_rental', 'Half Field', 'A smaller turf space for focused practices and group sessions.', '["Half of the turf field", "Daily rental hours: 6 AM\u201311 PM"]'::jsonb, null, null, null, true, 20),
('speed-agility', 'field_rental', 'Speed and Agility Space', 'A separate space for speed, movement, and skill development.', '["Separate training area", "Daily rental hours: 6 AM\u201311 PM"]'::jsonb, null, null, null, true, 30),
('turf-fun-party', 'birthday', 'Turf Fun Party', 'Party Package #1', '["1 hour of turf playtime", "30 minutes in the party area", "Up to 12 kids", "Soccer, kickball, dodgeball, flag football, or gagaball", "Field House party host included during games", "3 pizzas & 2 liters of soda", "Option to bring your own food"]'::jsonb, null, 90, 12, true, 40),
('ultimate-field-house-party', 'birthday', 'Ultimate Field House Party', 'Party Package #2', '["1 hour of turf playtime", "30 minutes in the party area", "Up to 16 kids", "Soccer, kickball, dodgeball, relay games, flag football, or gagaball", "Field House party host included during games", "4 pizzas & 2 liters of soda", "Option to bring your own food"]'::jsonb, null, 90, 16, true, 50);

create table public.booking_extras (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    unit_price_cents integer not null check (unit_price_cents >= 0),
    category text not null default 'birthday',
    published boolean not null default true
);
alter table public.booking_extras enable row level security;
revoke all on public.booking_extras from anon, authenticated;
grant select on public.booking_extras to anon, authenticated;
create policy "Read published booking extras" on public.booking_extras
    for select to anon, authenticated using (published);
insert into public.booking_extras (slug, name, unit_price_cents) values
('additional-child', 'Additional child', 1700),
('additional-pizza', 'Additional pizza', 2000),
('pizza-with-toppings', 'Additional pizza with toppings', 2200);

create table public.booking_line_items (
    id uuid primary key default gen_random_uuid(),
    booking_id uuid not null references public.bookings(id),
    extra_id uuid not null references public.booking_extras(id),
    quantity integer not null check (quantity > 0),
    unit_price_cents integer not null check (unit_price_cents >= 0)
);
alter table public.booking_line_items enable row level security;
revoke all on public.booking_line_items from anon, authenticated;

-- No public booking read/write access and no admin privileges granted yet.
-- Add a transaction-safe booking function before enabling confirmation.
commit;
