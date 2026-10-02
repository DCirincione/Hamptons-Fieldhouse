-- Retain offering IDs and historical bookings while updating rental options.
begin;

update public.offerings
set published = false
where slug = 'half-field';

update public.offerings
set name = 'Speed & Agility + Batting Cage',
    description = 'Train your speed, movement, and swing with one combined rental.',
    details = '["Speed and agility space and batting cage booked together", "Daily rental hours: 6 AM\u201311 PM"]'::jsonb,
    sort_order = 20
where slug = 'speed-agility';

commit;
