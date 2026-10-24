# Square-hosted booking checkout (Sandbox only)

Bookings paid successfully through Square are approved without staff review. A multi-date
request creates separate pending holds; paying for one session selects the earliest date,
and paying for all selects every date in that request. Customers can also pay an individual
upcoming unpaid booking from My Bookings, including a booking previously approved by staff.
A declined or incomplete hosted checkout never approves unpaid dates.
For Venmo, cash, and other manual methods, staff can use **Confirm & mark paid** or
**Mark as paid** after receiving full payment for the selected date. Processing Square
payments block these manual updates; completed Square payments cannot be overwritten.

## Configuration

The app reads `.env`, not `.env.local`. Configure:

```dotenv
SQUARE_ENVIRONMENT=sandbox
SQUARE_SANDBOX_ACCESS_TOKEN=...
SQUARE_SANDBOX_LOCATION_ID=...
SQUARE_BOOKING_PAYMENTS_ENABLED=true
SITE_URL=https://YOUR_HOST
```

Set `SITE_URL` to the public HTTPS origin so Square can return customers to My Bookings.

Apply `scripts/sql/square_booking_payments.sql` and then
`scripts/sql/square_hosted_booking_checkout.sql` before enabling checkout. Both scripts are
rerunnable and preserve bookings. The hosted-checkout migration adds the Square order/link
reference and a service-role-only function for attaching the hosted link to its locked
booking attempt. The private ledger and transactional functions prevent overlapping
payments and changes while a payment outcome is unresolved. Square access tokens stay on
the server.

Restart the development server after changing `.env`. Square Sandbox uses test cards and
no real money, but successful tests **do mark the selected database bookings paid and approved**.
Use test reservations. Production is deliberately unsupported: changing the environment to
`production` disables checkout. Do not expose Sandbox checkout to real customers.

## Hosted checkout and verification

The browser asks the server to create a Square Payment Link, then redirects the customer to
Square's HTTPS hosted checkout page. The server verifies session ownership and calculates
the total from database booking rows. A stale expected total rejects checkout. Square
receives a durable idempotency key, location, USD line item, and booking-ledger reference.
The order ID and HTTPS checkout URL are stored against the locked booking attempt. Only a
Square-verified payment with the matching order, amount, and location can mark its included
dates paid and confirmed. Returning from Square triggers a server-side order/payment check;
the signed webhook also reconciles completion if the customer closes the browser.

Retries reuse the original Square link and concurrent attempts cannot charge overlapping
dates. A declined payment leaves the same link available for another attempt. Unknown
outcomes retain their ledger/booking locks. My Bookings offers **Check payment status**.
Staff should inspect the Square order by its ledger reference and resolve its verified
result; never manually clear a processing attempt without checking Square. The site never
receives or stores full card data.

Cancellation after a completed payment still releases the booking and leaves its paid
status intact. Refunds remain a staff process; this change does not automate refunds or
mark a cancelled booking refunded. The UI tells customers to arrange refunds with staff.

## Webhooks and unattended recovery

Before public deployment, configure a reachable HTTPS webhook so completion reconciles if
the browser closes or the response is interrupted:

1. Set `SQUARE_WEBHOOK_URL=https://YOUR_HOST/api/square/webhook` to the **exact** subscription URL.
2. In the Square app's Sandbox Webhooks → Subscriptions, subscribe to `payment.created`
   and `payment.updated` at that URL.
3. Set `SQUARE_SANDBOX_WEBHOOK_SIGNATURE_KEY` to the subscription signature key.
4. Restart the server and send a Square test event.

The handler validates HMAC-SHA256 over the exact URL plus raw body with constant-time
comparison, then fetches the payment from Square instead of trusting event payment fields.
Duplicate deliveries are idempotent. Database failure returns an error so Square retries.
Do not use a localhost URL for a Square webhook. A public HTTPS tunnel is needed for local
webhook testing. Refund-event accounting and merchandise fulfillment are separate work.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PGLITE_PATH=/path/to/@electric-sql/pglite node tests/square_database.mjs
PYTHONPATH=. .venv/bin/python tests/browser_square.py
```

The browser suite mocks Square and booking storage. The isolated database suite tests
per-date approval, all-date approval, ownership, replay, overlap rejection, price changes,
cancellation guards, failure retries, and private permissions. Neither touches live bookings.

References: [Create payment link](https://developer.squareup.com/reference/square/checkout/create-payment-link),
[Retrieve order](https://developer.squareup.com/reference/square/orders-api/retrieve-order),
[Sandbox test cards](https://developer.squareup.com/docs/devtools/sandbox/payments),
[webhook signature verification](https://developer.squareup.com/docs/webhooks/step3validate),
[required CSP](https://developer.squareup.com/docs/web-payments/content-security-policy).
