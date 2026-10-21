# Square booking payments (Sandbox only)

Bookings paid successfully through Square are approved without staff review. A multi-date
request creates separate pending holds; paying for one session selects the earliest date,
and paying for all selects every date in that request. Customers can also pay an individual
upcoming unpaid booking from My Bookings, including a booking previously approved by staff.
A decline, closing the card dialog, or an incomplete payment never approves unpaid dates.
For Venmo, cash, and other manual methods, staff can use **Confirm & mark paid** or
**Mark as paid** after receiving full payment for the selected date. Processing Square
payments block these manual updates; completed Square payments cannot be overwritten.

## Configuration

The app reads `.env`, not `.env.local`. Configure:

```dotenv
SQUARE_ENVIRONMENT=sandbox
SQUARE_SANDBOX_ACCESS_TOKEN=...
SQUARE_SANDBOX_APPLICATION_ID=...
SQUARE_SANDBOX_LOCATION_ID=...
SQUARE_BOOKING_PAYMENTS_ENABLED=true
```

Apply `scripts/sql/square_booking_payments.sql` before enabling checkout. The script is
rerunnable, preserves bookings, and expects the existing customer booking schema including
`customer_user_id`. It adds a private payment ledger, transactional functions, and a guard
against cancellation or price changes while a payment outcome is unresolved. Only the
service role can read the ledger or execute payment functions. The token never reaches
browser JavaScript; only the application ID and location ID are public.

Restart the development server after changing `.env`. Square Sandbox uses test cards and
no real money, but successful tests **do mark the selected database bookings paid and approved**.
Use test reservations. Production is deliberately unsupported: changing the environment to
`production` disables checkout. Do not expose Sandbox checkout to real customers.

## Card form and verification

The browser loads Square's Sandbox Web Payments SDK on demand. It tokenizes the card with
buyer verification and a server-calculated amount. Card numbers never reach this server.
The payment endpoint verifies session ownership and uses database totals, not a browser
price. A stale expected total rejects the payment before charging. Square receives an
immutable payment request with a durable idempotency key, selected location, USD amount,
and ledger reference. Only a server-verified CARD payment in COMPLETED state with the
matching amount, location, and reference can mark the included dates paid and confirmed.

Retries reuse the original request and source token; concurrent attempts cannot charge
an overlapping date. Definite declines release dates for another payment attempt. Unknown
outcomes retain their ledger/booking locks. The dialog and profile offer **Check payment
status**. Payment retries older than one hour stop for staff reconciliation instead of
risking a new charge. Staff should inspect the Square payment by its ledger reference and
resolve its verified result; never manually clear a processing attempt without checking
Square. A completed/failed attempt wipes its stored source token. No full card data is stored.

Cancellation after a completed payment still releases the booking and leaves its paid
status intact. Refunds remain a staff process; this change does not automate refunds or
mark a cancelled booking refunded. The UI tells customers to arrange refunds with staff.

## Webhooks and unattended recovery

Local checkout can finish synchronously and recover through Check payment status. Before
public deployment, configure a reachable HTTPS webhook so completion still reconciles if
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

References: [Web Payments SDK](https://developer.squareup.com/docs/web-payments/quickstart/add-sdk-to-web-client),
[CreatePayment](https://developer.squareup.com/reference/square/payments-api/create-payment),
[Sandbox test cards](https://developer.squareup.com/docs/devtools/sandbox/payments),
[webhook signature verification](https://developer.squareup.com/docs/webhooks/step3validate),
[required CSP](https://developer.squareup.com/docs/web-payments/content-security-policy).
