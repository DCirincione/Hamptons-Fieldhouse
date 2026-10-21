-- Run once in the Supabase SQL editor.
alter table public.contact_messages
  add column if not exists read_at timestamptz;

create index if not exists contact_messages_read_at_idx
  on public.contact_messages (read_at);
