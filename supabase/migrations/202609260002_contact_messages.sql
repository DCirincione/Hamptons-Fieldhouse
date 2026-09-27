-- Run in the Supabase SQL Editor to enable the contact form.
create table public.contact_messages (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    first_name text not null check (length(trim(first_name)) between 1 and 100),
    last_name text not null check (length(trim(last_name)) between 1 and 100),
    phone_number text not null check (length(phone_number) between 7 and 30),
    email text not null check (length(email) between 3 and 254 and position('@' in email) > 1),
    message text not null check (length(trim(message)) between 1 and 5000)
);
alter table public.contact_messages enable row level security;
revoke all on public.contact_messages from anon, authenticated;
grant insert (first_name, last_name, phone_number, email, message)
    on public.contact_messages to anon, authenticated;
create policy "Visitors can submit contact messages"
    on public.contact_messages for insert to anon, authenticated with check (true);
-- No public read/update/delete access. View messages in the Supabase dashboard.
