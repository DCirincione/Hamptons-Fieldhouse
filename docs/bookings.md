# Book & Register

The layout is available at `/space-rentals`. It reads published `offerings` from
Supabase. Until the table is available, it falls back to the approved local catalog
in `app/data/offerings.json`. Missing prices display as TBD; no camp dates are invented.
An empty published catalog stays empty rather than bringing back hidden offerings.

## Database setup

Run `supabase/migrations/202609260003_bookings.sql` in Supabase SQL Editor.
The migration has not been applied automatically. It creates:

- `offerings`: rentals, party packages, camps, clinics, and events, with publication
  state, integer-cent prices, durations, capacity, descriptions, and detail lists.
- `program_sessions`: scheduled programs with start/end timestamps and capacity.
- `bookings`: private customer information and confirmed/cancelled booking records.
- `booking_extras`: the supplied per-child and pizza prices.
- `booking_line_items`: quantities and price snapshots for selected extras.

The seed includes the three rental spaces, both supplied birthday packages, and
three extras. Base prices and rental durations remain null (TBD). Contact messages
stay in the existing `contact_messages` table.

## Next phase: immediate confirmation

The intended flow confirms bookings immediately. The current page is a layout
preview, not a reservation or payment system. Buttons show a details dialog and
phone contact; no personal data is collected or booking claimed.

Before enabling confirmation, specify rates, slot lengths, booking horizons, and
space-sharing rules: full-field versus half-field conflicts, how many halves can
run concurrently, and which resources parties occupy during their turf and party
area periods. Implement an atomic database booking function that validates prices,
capacity, resource overlaps, and line items before confirming. All scheduling uses
America/New_York. Add program session selection and participant registration then.

Public clients may read published catalog data but cannot read or write bookings.
The future dashboard needs explicit authenticated admin authorization policies;
ordinary signed-in users must not gain admin access. Keep service-role keys server-side.
