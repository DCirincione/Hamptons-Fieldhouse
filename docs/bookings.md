# Book & Register

`/space-rentals` contains the rental and birthday catalog, a service-specific month
calendar popup opened from each rental or party card, available time blocks,
pricing review, and a booking request form.
`/admin/bookings` is the staff approval queue.

## Booking rules

Confirmed with the client October 1, 2026:

- Full Field and Speed & Agility + Batting Cage are independent rental spaces.
  Speed/agility and the batting cage are always one combined rental.
- Rental hours: daily 6 AM–11 PM; standard rental blocks: 60 minutes.
- Birthday parties: 60 minutes on the full field, followed by 30 minutes in the
  party area. The field becomes available after the first hour. Both birthday
  packages share these same resources and cannot double-book them.
- Venmo/other payment methods require staff approval. Submitting a request holds
  its resources immediately. Approval retains the hold; cancellation/decline
  releases it. Holds do not expire automatically.
- Square is not integrated. In the future, verified successful Square payments
  should confirm automatically through a separate server-side payment flow.

Editable implementation defaults: starts on the hour, at least one hour's notice,
up to 90 days ahead. Last rental start is 10 PM; last party start is 9 PM (ends
10:30 PM). Custom durations require contacting staff. All dates/times are interpreted
in `America/New_York`, including daylight saving time.

## Rates and packages

- Full Field: $200/hour; combined backspace: $75/hour. Both await Raf's final
  confirmation; the catalog labels them accordingly.
- Turf and Fun Party: $445 for up to 12 kids, 3 pizzas and 2 liters of soda;
  bring-your-own-food discount $50 ($395 before extras).
- Ultimate Fieldhouse Party: $545 for up to 16 kids, 4 pizzas and 2 liters of soda;
  bring-your-own-food discount $60 ($485 before extras).
- Additional children: $17 each. Additional pizzas with toppings: $22 each.
  Food discounts affect the package; selected extra pizzas are still charged.
- Customers bring their own cake and decorations.

Prices are calculated again in the database, with the displayed expected total
checked before reserving. Changed prices require a refreshed review. Booking extras
store quantity and price snapshots; food discounts are stored on the booking.
Payment status remains `unpaid`; approving a booking does not record a payment.

## Setup and activation

Apply these migrations in order in Supabase SQL Editor (not automatically applied):

1. `supabase/migrations/202609260003_bookings.sql`
2. `supabase/migrations/202610010001_rental_options.sql`
3. `supabase/migrations/202610010002_pricing_and_packages.sql`
4. `supabase/migrations/202610010003_booking_calendar.sql`
5. `supabase/migrations/202610010004_staff_schedule.sql`

The fourth migration backfills existing reservations conservatively and fails on
conflicting legacy bookings so they can be reconciled before launch. Existing
custom rental durations retain their full occupied interval. It adds resource
exclusion constraints, request idempotency, pending status, private settings,
staff action records, and restricted database functions. Pending and confirmed
reservations both occupy resource slots.

Configure server-only environment variables:

- `SUPABASE_URL`: the project URL (already used by the catalog).
- `SUPABASE_KEY`: the existing catalog/contact key.
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key for booking RPCs and staff
  reads. Never expose this in browser code.
- `SITE_URL`: the public origin, such as `https://your-domain.com` (local default:
  `http://localhost:8000`). Add `SITE_URL/account` to the Supabase Auth redirect
  allowlist. Enable email/password sign-up and email confirmation in Supabase Auth.

The old `BOOKING_ADMIN_TOKEN` is no longer used. Staff sign in with individual
accounts at `/account`; confirmed accounts with `app_metadata.role = "admin"`
can access the staff page and APIs. Regular accounts cannot read or change staff
bookings, even by calling APIs directly. Users cannot assign themselves an admin
role through signup or user-editable metadata.

To grant the first administrator after they create and confirm their account:

```sh
.venv/bin/python scripts/manage_admin.py --email danny.cirincione@gmail.com --role admin
```

For additional staff, use the same trusted server command with their email. To
revoke access, use `--role member`. Omitting `--role` inspects that account only.
This tool requires the server's Supabase service role key and does not send email
or create accounts. It preserves unrelated app metadata. Permission is checked
against Supabase's verified user on every protected request, so role removal does
not wait for a browser's old JWT claim to expire.

Sessions use HttpOnly SameSite=Lax cookies (Secure outside local development),
with server-side refresh. Tokens are never returned to browser JavaScript or
saved in local storage. Auth and staff writes require a custom same-origin header
and reject cross-site origins. Account-specific responses are not cached.
See [Supabase user metadata](https://supabase.com/docs/guides/auth/users) and
[verified server-side sessions](https://supabase.com/docs/guides/auth/server-side/advanced-guide).

After verifying final rates, existing reservations, and the scheduling defaults,
enable booking:

```sql
update public.booking_policy set enabled = true where id;
```

Booking deliberately starts disabled until this activation step. With missing
configuration, migrations, or database access, the calendar shows an unavailable
message and phone contact; it never substitutes invented available times. The
local JSON fallback is used for catalog cards only. Serve production over HTTPS.

## Staff workflow

1. Sign in at `/account`, then open **Booking Admin** from the header profile
   dropdown. This link appears only for accounts with admin permission.
2. Review pending requests and contact the customer to arrange/verify payment.
3. Approve the request, or cancel it to release the time. Confirmed bookings can
   also be cancelled. A cancelled booking must be rebooked to reinstate it.
4. Tell the customer the outcome directly. **No automatic emails or SMS are sent.**
   Customers see an on-screen reference and pending approval receipt.

The queue shows up to 500 active bookings. A staff refresh retrieves the latest
state; customer calendars refresh on service/month changes and have a manual
refresh button. Every submission rechecks availability atomically. A retry with
the same request ID and identical details returns the same booking; altered
payloads using an existing ID are rejected.

## Staff schedule controls

The **Manage available times** section in `/admin/bookings` shows a selected day
and space, open by default from 6 AM–11 PM. Reserved hours are crossed out; the
list underneath shows exact intervals and whether they are pending bookings,
approved bookings, or staff-entered blocks. A partial-hour reservation marks that
hour occupied, while exact times remain visible in the list.

- Click an open hour to prefill a block, or enter any minute-level time range.
- Choose one or more spaces and a private customer/reason label.
- Use **Individual dates and times** to enter several appointments with different
  times, **Repeat every day**, or **Repeat on selected weekdays** for regulars.
- Repeats require an inclusive end date within the next year. Dates are expanded
  server-side in America/New_York, preserving local time across DST changes.
- A whole series is saved atomically. Any conflict with an existing reservation or
  block rejects the entire batch; no dates are silently skipped.
- **Release this time** removes that occurrence from all its selected spaces;
  **Remove entire series** removes all occurrences from all spaces in the series.
- Customer reservations must be cancelled through the booking queue. They cannot
  be removed using the block controls.

These staff blocks are immediately effective; they do not need approval, create
payments, or send notifications. The label is staff-only and never appears on
public calendars. Blocks do not expire. The initial public 90-day booking horizon
still applies, even when staff enter a recurring schedule up to a year ahead.

The booking API never returns customer data through availability. Public Supabase roles cannot read
private booking tables or execute reservation/staff functions. Use deployment
rate limits for public submissions and staff sign-in before public launch.

## Verification

API validation and authorization tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Database migration and scheduling tests use an isolated PostgreSQL WASM runtime,
not a live Supabase project:

```sh
npm install --prefix /tmp/fieldhouse-booking-check @electric-sql/pglite@0.5.8
PGLITE_PATH=/tmp/fieldhouse-booking-check/node_modules/@electric-sql/pglite node tests/booking_database.mjs
```

Browser checks use installed Chrome and mocked API responses, verifying the
customer and staff flows at desktop/mobile sizes:

```sh
PYTHONPATH=. .venv/bin/python tests/browser_bookings.py
```

Database design references: [PostgreSQL range exclusion constraints](https://www.postgresql.org/docs/15/rangetypes.html)
and [Supabase function permissions](https://supabase.com/docs/guides/database/functions).

## Camps, clinics, waivers, and merchandise

The future camp/clinic admin portal should support title, flyer, description,
dates, and cost. Registration must collect name, phone, email, and a signed waiver.
Camp registration is separate from the rental/party reservation flow implemented
here and is not yet enabled.

Continue using https://www.hamptonsfieldhouse.com/waiver. The site links to that
page; it does not verify completion or attach signed waivers to registrations.
If the original domain moves to this app, preserve the waiver route or obtain
the provider's permanent URL first.

Printful store/account details are still pending from the client.
