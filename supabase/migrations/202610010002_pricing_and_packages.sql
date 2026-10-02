-- Client-supplied rates and packages; rental rates await final confirmation.
begin;

update public.offerings set
    name = 'Full Field',
    details = '["Full turf field", "Daily rental hours: 6 AM\u201311 PM", "Standard rentals are booked in 1-hour blocks", "Contact us for custom durations and pricing", "Rental rate subject to confirmation"]'::jsonb,
    price_cents = 20000,
    duration_minutes = 60
where slug = 'full-field';

update public.offerings set
    name = 'Speed & Agility + Batting Cage',
    details = '["Speed and agility space and batting cage booked together", "Daily rental hours: 6 AM\u201311 PM", "Standard rentals are booked in 1-hour blocks", "Contact us for custom durations and pricing", "Rental rate subject to confirmation"]'::jsonb,
    price_cents = 7500,
    duration_minutes = 60
where slug = 'speed-agility';

update public.offerings set
    name = 'Turf and Fun Party',
    details = '["1 hour of turf playtime", "30 minutes in the party area", "Up to 12 kids", "Soccer, kickball, dodgeball, flag football, or gaga ball", "Fieldhouse party host included during games", "3 pizzas & 2 liters of soda", "Bring your own food and save $50"]'::jsonb,
    price_cents = 44500,
    duration_minutes = 90
where slug = 'turf-fun-party';

update public.offerings set
    name = 'Ultimate Fieldhouse Party',
    details = '["1 hour of turf playtime", "30 minutes in the party area", "Up to 16 kids", "Soccer, kickball, dodgeball, relay games, flag football, or gaga ball", "Fieldhouse party host included during games", "4 pizzas & 2 liters of soda", "Bring your own food and save $60"]'::jsonb,
    price_cents = 54500,
    duration_minutes = 90
where slug = 'ultimate-field-house-party';

-- Only the supplied $22 pizza-with-toppings extra is currently advertised.
update public.booking_extras set published = false where slug = 'additional-pizza';
update public.booking_extras set unit_price_cents = 2200 where slug = 'pizza-with-toppings';

-- Bring-your-own-food discounts are package-specific; apply them in the
-- future booking calculation, not as negative-price extras.
commit;
