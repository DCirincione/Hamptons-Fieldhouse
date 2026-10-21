# Book & Register

`/space-rentals` contains the rental and birthday catalog, a service-specific month
calendar popup opened from each rental or party card, available time blocks,
pricing review, and a booking request form.
`/admin/bookings` is the staff approval queue.

## Booking rules

Confirmed with the client October 1, 2026:

- Full Field and Speed & Agility + Batting Cage are independent rental spaces.
  Speed/agility and the batting cage are always one combined rental.
- Default rental hours: daily 6 AM–11 PM, editable by staff; standard rental blocks: 60 minutes.
- Birthday parties: 60 minutes on the full field, followed by 30 minutes in the
  party area. The field becomes available after the first hour. Both birthday
  packages share these same resources and cannot double-book them.
- Venmo/cash/other payment methods require staff approval. Submitting a request holds
  its resources immediately. Approval retains the hold; cancellation/decline
  releases it. Holds do not expire automatically.
- Square Sandbox card checkout is implemented behind `SQUARE_BOOKING_PAYMENTS_ENABLED`.
  Verified completed payments mark only their included dates paid and confirmed.
  Paying for one session covers the earliest selected date; paying for all covers every selected date.
  Unpaid dates continue to need staff approval. See [Square setup](square.md).

Editable implementation defaults: starts on the hour, at least one hour's notice,
up to 90 days ahead. Starts must fit entirely within the effective hours for that date. With the default schedule, the last rental starts at 10 PM and the last party at 9 PM (ends 10:30 PM). Custom durations require contacting staff. All dates/times are interpreted
in `America/New_York`, including daylight saving time.

## Customer accounts and approval tracking

`/account` now includes **My Bookings** and **My Profile**. Customers can update
name and phone; the sign-in email is displayed read-only. Signup also accepts a
phone number. Profile edits cannot modify admin permission or another account.

New booking submissions require an email-confirmed session and are linked to
its immutable user ID. Booking email is taken from that verified account on the
server. Public availability browsing remains available without an account.
Older bookings may remain unlinked; contact staff to reconcile those records.
Later email changes do not transfer ownership of already-linked bookings.

The dashboard displays upcoming bookings and past/cancelled bookings, with
**Pending approval**, **Approved**, or **Cancelled** for each date. It retrieves
only the signed-in user's rows, 50 per page, and refreshes every 20 seconds while
visible, on returning to the page, or using Refresh. This is polling, not a push
notification or email service. Payment labels remain separate from approval:
Venmo/cash payment is arranged with staff, and approval does not automatically
mark a payment as collected.

Customers can repeat their selected time on exact dates chosen on the calendar, up to 30 dates per request within the existing booking horizon. Each
occurrence preserves Eastern local time across DST and creates its own pending
reservation for staff review. The full request is atomic: one unavailable date or
changed price rolls back all new dates. Retries with the same request key are
idempotent and owner-checked. The review shows per-date and full-series totals.
Repeated requests offer payment for one session now or all sessions now. The choice
and calculated initial amount are saved in the request payload and shown to staff.
For manual methods this remains a payment preference. Square checkout charges the selected dates only;
a browser selection or successful tokenization is never treated as proof of payment.
The admin queue identifies repeating requests; staff approves/cancels individual
dates, with changes appearing on the customer's next refresh.

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
Plain staff approval leaves payment status `unpaid`. Staff can choose **Confirm & mark paid**
for a pending manual-payment booking, or **Mark as paid** for an already confirmed one.
These actions record full payment received for that date without charging the customer. A verified completed Square payment marks its dates `paid` and `confirmed`.

## Setup and activation

Database schema and deployment changes are managed outside this repository.
For the editable-hours feature, apply `scripts/sql/availability_hours.sql` to the
existing booking database before deploying this application version. It adds
weekly hours and date overrides and updates availability and staff block RPCs.
The SQL is a deployment artifact; it has not been applied automatically. It
expects the existing booking-policy, resource-slot, and staff-series schema.
The existing reservation RPC must retain its shared lock on `booking_policy` and
call `booking_availability`; hours writes take an exclusive lock on the same row
so concurrent reservations and hours changes serialize. Verify those contracts
against the externally managed schema before applying.
Pending and confirmed reservations both occupy resource slots.

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

The **Calendar & Bookings** section combines date selection and booking review.
A yellow exclamation mark means a date has appointments awaiting confirmation;
a green checkmark indicates confirmed bookings or manually booked times. The tooltip includes the number of booked appointments, counting a party
or multi-space manual occurrence once rather than once per space.
Selecting a date shows compact entries. Open a customer entry to confirm or
cancel it. Manual entries say **Booked**; opening one reveals **Manually blocked**,
the staff reason, and release controls. There is no open-hour grid in this view.
Use **Block time** to open the form for individual or repeating manual reservations.

Weekly hours show common opening/closing times and an **Apply to all days** action.
Each weekday is collapsed by default and expands for custom hours or closure.
**Change hours for this date** overrides the weekly schedule for one date;
**Use weekly hours** removes that override. Existing bookings are preserved.
Hours load independently of bookings and reserved slots, so a schedule failure
does not lock the hours editor. The schedule now reads protected resource slots
directly and does not depend on the older `staff_schedule` RPC or `series_id` column.
Monthly booking queries retrieve all pages, using Eastern month boundaries.

On older installations missing `booking_block_series` or `series_id`, apply
`scripts/sql/repair_manual_blocks.sql` to enable manual block creation and release.
This rerunnable repair preserves hours, bookings, and existing blocks. It is
separate from the already-applied hours update. Calendar reads and hours editing
do not require this repair. The calendar uses booking status. Staff confirmation does not mark a payment paid;
verified Square payment completion does.

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

Browser checks use installed Chrome and mocked API responses, verifying the
customer and staff flows at desktop/mobile sizes:

```sh
PYTHONPATH=. .venv/bin/python tests/browser_bookings.py
```


The hours migration can also be checked in an isolated PostgreSQL runtime, using
`tests/hours_database.mjs`. Set `PGLITE_PATH` to a temporary installation of
`@electric-sql/pglite` and `BOOKING_SCHEMA_DIR` to the baseline booking SQL directory
(the four migrations named in the test). The check covers closed days, weekly
hours, date overrides/reset, stale booking rejection, retained reservations,
expanded staff block hours, duration boundaries, and RPC permissions. This is a
local schema test, not verification of the live externally managed database.

## Camps, clinics, waivers, and merchandise

The future camp/clinic admin portal should support title, flyer, description,
dates, and cost. Registration must collect name, phone, email, and a signed waiver.
Camp registration is separate from the rental/party reservation flow implemented
here and is not yet enabled.

Continue using https://www.hamptonsfieldhouse.com/waiver. The site links to that
page; it does not verify completion or attach signed waivers to registrations.
If the original domain moves to this app, preserve the waiver route or obtain
the provider's permanent URL first.

Printful catalog browsing is connected. Merchandise checkout and fulfillment remain disabled;
this Square change implements booking payments only.

Customers can cancel their own upcoming pending or approved bookings from My Bookings.
Cancellation applies to one date, releases its resource slots atomically, and leaves
payment status unchanged. Refunds are arranged with staff. Past/started bookings
cannot be cancelled through the customer endpoint.
