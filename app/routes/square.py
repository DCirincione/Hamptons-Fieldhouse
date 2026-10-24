"""Square booking payments. Only verified Square completion approves dates."""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.auth import verified_customer
from app.config import Settings, get_settings
from app.routes.bookings import get_booking_db
from app.routes.contact import ContactMessage

router = APIRouter(prefix='/square', tags=['payments'])


def square_credentials(settings):
    if settings.square_environment == 'production':
        return {
            'access_token': settings.square_production_access_token.get_secret_value(),
            'application_id': settings.square_production_application_id,
            'location_id': settings.square_production_location_id,
            'webhook_signature_key': settings.square_production_webhook_signature_key.get_secret_value(),
            'api_base': 'https://connect.squareup.com/v2',
        }
    return {
        'access_token': settings.square_sandbox_access_token.get_secret_value(),
        'application_id': settings.square_sandbox_application_id,
        'location_id': settings.square_sandbox_location_id,
        'webhook_signature_key': settings.square_sandbox_webhook_signature_key.get_secret_value(),
        'api_base': 'https://connect.squareupsandbox.com/v2',
    }


def credentials_configured(settings):
    credentials = square_credentials(settings)
    return bool(credentials['access_token']) and bool(credentials['location_id'])


def configured(settings):
    return settings.square_booking_payments_enabled and credentials_configured(settings)


def require_square(settings):
    if not configured(settings):
        raise HTTPException(503, 'Square checkout is not available yet.')


def square_request(settings, method, path, body=None):
    if not credentials_configured(settings):
        raise HTTPException(503, 'Square is not configured yet.')
    credentials = square_credentials(settings)
    try:
        response = httpx.request(method, credentials['api_base'] + path,
            headers={'Authorization': 'Bearer ' + credentials['access_token'],
                     'Square-Version': '2026-09-16'}, json=body, timeout=25)
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Payment status is uncertain. Check payment status before trying another payment.') from None
    return response.status_code, data


def db_rpc(db, name, params):
    try:
        return db.rpc(name, params).execute().data
    except APIError as exc:
        if exc.code in ('22023', 'P0001'):
            raise HTTPException(409, 'These dates are no longer payable or a payment is processing. Refresh My Bookings and check payment status.') from None
        if exc.code in ('PGRST202', 'PGRST204', '42883', '42703'):
            raise HTTPException(503, 'Square checkout needs a database update. Apply scripts/sql/square_hosted_booking_checkout.sql in Supabase, then retry from My Bookings.') from None
        raise HTTPException(503, 'Payment records are unavailable. Check payment status before retrying.') from None
    except httpx.HTTPError:
        raise HTTPException(503, 'Payment records are unavailable. Check payment status before retrying.') from None


class Dates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    booking_ids: list[UUID] = Field(min_length=1, max_length=30)


class Charge(Dates):
    request_id: UUID
    expected_amount_cents: int = Field(gt=0, strict=True)
    source_id: str = Field(min_length=1, max_length=2048)


class HostedCheckout(Dates):
    request_id: UUID


class CampRegistration(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    request_id: UUID
    service_slug: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    session_label: str = Field(min_length=1, max_length=240)
    price_label: str = Field(min_length=1, max_length=80)
    guardian_name: str = Field(min_length=2, max_length=160)
    guardian_email: EmailStr = Field(max_length=254)
    guardian_phone: str = Field(min_length=7, max_length=30)
    participant_name: str = Field(min_length=2, max_length=160)
    participant_grade: str = Field(min_length=1, max_length=80)
    waiver_confirmed: bool

    @field_validator('guardian_phone')
    @classmethod
    def valid_phone(cls, value: str) -> str:
        return ContactMessage.validate_phone(value)


def payable_rows(db, user, ids):
    ids = [str(i) for i in ids]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, 'Choose each date once.')
    try:
        rows = db.table('bookings').select('id,total_price_cents,starts_at,status,payment_status,square_attempt_id').eq(
            'customer_user_id', str(user.id)).in_('id', ids).execute().data
    except (APIError, httpx.HTTPError):
        raise HTTPException(503, 'Could not check your booking totals.') from None
    if len(rows) != len(ids) or any(r['status'] not in ('pending', 'confirmed') or r['payment_status'] != 'unpaid'
            or r.get('square_attempt_id') or datetime.fromisoformat(r['starts_at'].replace('Z','+00:00')) <= datetime.now(timezone.utc) for r in rows):
        raise HTTPException(409, 'One or more dates are no longer payable. Refresh My Bookings.')
    return rows


@router.get('/config')
def config(response: Response, settings: Settings = Depends(get_settings)):
    response.headers['Cache-Control'] = 'no-store'
    return {'enabled': bool(configured(settings)), 'environment': settings.square_environment}


@router.post('/quote')
def quote(data: Dates, user=Depends(verified_customer), db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    ids = [str(value) for value in data.booking_ids]
    try:
        rows = db.table('bookings').select('id,square_attempt_id').eq('customer_user_id', str(user.id)).in_('id', ids).execute().data
        attempt_ids = {row.get('square_attempt_id') for row in rows}
        if len(rows) == len(ids) and len(attempt_ids) == 1 and None not in attempt_ids:
            existing = db.table('booking_square_payments').select('*').eq('id', next(iter(attempt_ids))).execute().data
            if (existing and existing[0].get('status') == 'processing'
                    and not existing[0].get('source_id')
                    and sorted(existing[0].get('booking_ids', [])) == sorted(ids)):
                return {'amount_cents': existing[0]['amount_cents'], 'currency': 'USD',
                        'date_count': len(ids), 'billing_contact': {'email': user.email}}
    except (APIError, httpx.HTTPError):
        raise HTTPException(503, 'Could not check your booking totals.') from None
    rows = payable_rows(db, user, data.booking_ids)
    metadata = getattr(user, 'user_metadata', {}) or {}
    names = str(metadata.get('name', '')).split(maxsplit=1)
    contact = {'email': user.email}
    if names:
        contact['givenName'] = names[0]
    if len(names) > 1:
        contact['familyName'] = names[1]
    if metadata.get('phone_number'):
        contact['phone'] = metadata['phone_number']
    return {'amount_cents': sum(r['total_price_cents'] for r in rows), 'currency': 'USD',
            'date_count': len(rows), 'billing_contact': contact}


@router.post('/checkout')
def hosted_checkout(data: HostedCheckout, user=Depends(verified_customer),
                    db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    ids = [str(value) for value in data.booking_ids]
    # Do one read to reuse a previous attempt or calculate the amount. The
    # begin-payment RPC repeats all payable/ownership/amount checks atomically.
    try:
        rows = db.table('bookings').select(
            'id,total_price_cents,starts_at,status,payment_status,square_attempt_id'
        ).eq('customer_user_id', str(user.id)).in_('id', ids).execute().data
    except (APIError, httpx.HTTPError):
        raise HTTPException(503, 'Could not check your booking payment.') from None
    credentials = square_credentials(settings)
    attempt = None
    if len(rows) == len(ids) and rows and all(row.get('square_attempt_id') for row in rows):
        attempt_ids = {row['square_attempt_id'] for row in rows}
        if len(attempt_ids) == 1:
            try:
                existing = db.table('booking_square_payments').select('*').eq('id', next(iter(attempt_ids))).execute().data
            except (APIError, httpx.HTTPError):
                raise HTTPException(503, 'Could not check your booking payment.') from None
            if (existing and existing[0].get('status') == 'processing'
                    and sorted(existing[0].get('booking_ids', [])) == sorted(ids)):
                attempt = existing[0]
                if attempt.get('source_id'):
                    raise HTTPException(409, 'A card payment is already processing. Check payment status before starting another payment.')
                if attempt.get('square_order_id') and attempt.get('payment_link_url'):
                    return {'checkout_url': attempt['payment_link_url']}
            elif existing:
                raise HTTPException(409, 'This booking is part of a different or completed Square checkout. Refresh My Bookings.')
    if attempt is None:
        payable = [row for row in rows if row.get('status') in ('pending', 'confirmed')
                   and row.get('payment_status') == 'unpaid' and not row.get('square_attempt_id')
                   and datetime.fromisoformat(row['starts_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)]
        if len(payable) != len(ids):
            raise HTTPException(409, 'One or more dates are no longer payable. Refresh My Bookings.')
        amount_cents = sum(row['total_price_cents'] for row in payable)
        attempt = db_rpc(db, 'begin_booking_square_payment', {
            'p_id': str(data.request_id), 'p_user_id': str(user.id), 'p_booking_ids': ids,
            'p_source': '', 'p_location': credentials['location_id'], 'p_expected': amount_cents})
    if attempt.get('square_order_id') and attempt.get('payment_link_url'):
        return {'checkout_url': attempt['payment_link_url']}
    options = {}
    site = urlparse(settings.site_url)
    if site.scheme == 'https' and site.hostname:
        options['redirect_url'] = settings.site_url.rstrip('/') + '/account?booking_checkout=complete'
    code, result = square_request(settings, 'POST', '/online-checkout/payment-links', {
        'idempotency_key': attempt['id'],
        'description': f"Hamptons Fieldhouse booking {attempt['id']}",
        'payment_note': f"Fieldhouse booking {attempt['id']}",
        'order': {
            'location_id': credentials['location_id'],
            'reference_id': attempt['id'],
            'line_items': [{
                'name': f"Fieldhouse booking · {len(ids)} date{'s' if len(ids) != 1 else ''}",
                'quantity': '1',
                'base_price_money': {'amount': attempt['amount_cents'], 'currency': 'USD'},
            }],
            'pricing_options': {'auto_apply_taxes': False},
        },
        'checkout_options': options,
    })
    link = result.get('payment_link', {})
    order_id, checkout_url = link.get('order_id'), link.get('url')
    parsed = urlparse(checkout_url or '')
    allowed_hosts = {'sandbox.square.link'} if settings.square_environment == 'sandbox' else {'square.link', 'checkout.square.site'}
    if (code not in (200, 201) or not order_id or parsed.scheme != 'https'
            or parsed.hostname not in allowed_hosts):
        raise HTTPException(502, 'Square could not start secure checkout. Your booking is still held; try again or check payment status.')
    attempt = db_rpc(db, 'attach_booking_square_link', {
        'p_id': attempt['id'], 'p_order_id': order_id, 'p_url': checkout_url})
    return {'checkout_url': attempt['payment_link_url']}


@router.post('/camp-checkout')
def camp_checkout(data: CampRegistration, db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    if not data.waiver_confirmed:
        raise HTTPException(422, 'A parent or guardian must confirm the participant waiver before registering.')
    try:
        offerings = db.table('offerings').select('id,name,category,published,program_data').eq(
            'slug', data.service_slug).limit(1).execute().data
        if not offerings or not offerings[0]['published'] or offerings[0]['category'] not in ('camp', 'clinic'):
            raise HTTPException(404, 'This program is not accepting registrations right now.')
        offering = offerings[0]
        program = offering.get('program_data') or {}
        if data.session_label not in (program.get('sessions') or []):
            raise HTTPException(409, 'That session is no longer available. Refresh the page and try again.')
        selected = next((option for option in (program.get('price_options') or [])
                         if option.get('label') == data.price_label), None)
        if not selected or int(selected.get('price_cents') or 0) <= 0:
            raise HTTPException(409, 'That registration option is no longer available. Refresh the page and try again.')
        amount_cents = int(selected['price_cents'])
        existing = db.table('camp_registrations').select('*').eq('request_id', str(data.request_id)).limit(1).execute().data
        registration = existing[0] if existing else None
        if registration:
            same = (registration['offering_id'] == offering['id']
                    and registration['session_label'] == data.session_label
                    and registration['price_label'] == data.price_label
                    and registration['amount_cents'] == amount_cents
                    and registration['guardian_name'] == data.guardian_name
                    and registration['guardian_email'].casefold() == str(data.guardian_email).casefold()
                    and registration['guardian_phone'] == data.guardian_phone
                    and registration['participant_name'] == data.participant_name
                    and registration['participant_grade'] == data.participant_grade)
            if not same:
                raise HTTPException(409, 'This registration request has already been used. Refresh the form and try again.')
        else:
            row = {
                'id': str(data.request_id), 'request_id': str(data.request_id), 'offering_id': offering['id'],
                'session_label': data.session_label, 'price_label': data.price_label, 'amount_cents': amount_cents,
                'guardian_name': data.guardian_name, 'guardian_email': str(data.guardian_email),
                'guardian_phone': data.guardian_phone, 'participant_name': data.participant_name,
                'participant_grade': data.participant_grade, 'waiver_confirmed': True,
            }
            try:
                db.table('camp_registrations').insert(row).execute()
            except APIError as exc:
                if exc.code in ('PGRST205', 'PGRST204', '42P01', '42703'):
                    raise HTTPException(503, 'Camp registration needs a database update. Rerun scripts/sql/dynamic_booking_offerings.sql in Supabase.') from None
                if exc.code not in ('23505', '409'):
                    raise
                existing = db.table('camp_registrations').select('*').eq('request_id', str(data.request_id)).limit(1).execute().data
                if not existing:
                    raise
                registration = existing[0]
        registration = db.table('camp_registrations').select('*').eq('request_id', str(data.request_id)).limit(1).execute().data[0]
        same = (registration['offering_id'] == offering['id']
                and registration['session_label'] == data.session_label
                and registration['price_label'] == data.price_label
                and registration['amount_cents'] == amount_cents
                and registration['guardian_name'] == data.guardian_name
                and registration['guardian_email'].casefold() == str(data.guardian_email).casefold()
                and registration['guardian_phone'] == data.guardian_phone
                and registration['participant_name'] == data.participant_name
                and registration['participant_grade'] == data.participant_grade)
        if not same:
            raise HTTPException(409, 'This registration request has already been used. Refresh the form and try again.')
        if registration['status'] == 'paid':
            raise HTTPException(409, 'This registration has already been paid.')
        if registration['status'] == 'payment_failed':
            raise HTTPException(409, 'Payment did not complete. Refresh the registration form to try again.')
        if registration.get('payment_link_url'):
            return {'checkout_url': registration['payment_link_url']}
        credentials = square_credentials(settings)
        options = {}
        site = urlparse(settings.site_url)
        if site.scheme == 'https' and site.hostname:
            options['redirect_url'] = settings.site_url.rstrip('/') + '/space-rentals?camp_registration=complete'
        code, result = square_request(settings, 'POST', '/online-checkout/payment-links', {
            'idempotency_key': str(data.request_id),
            'description': f"{offering['name']} · {data.price_label}",
            'payment_note': f"Camp registration {data.request_id}",
            'pre_populated_data': {'buyer_email': str(data.guardian_email)},
            'order': {
                'location_id': credentials['location_id'], 'reference_id': str(data.request_id),
                'line_items': [{
                    'name': f"{offering['name']} · {data.price_label} · {data.session_label}",
                    'quantity': '1',
                    'base_price_money': {'amount': amount_cents, 'currency': 'USD'},
                }],
                'pricing_options': {'auto_apply_taxes': False},
            },
            'checkout_options': options,
        })
        link = result.get('payment_link', {})
        order_id, checkout_url = link.get('order_id'), link.get('url')
        parsed = urlparse(checkout_url or '')
        allowed_hosts = {'sandbox.square.link'} if settings.square_environment == 'sandbox' else {'square.link', 'checkout.square.site'}
        if code not in (200, 201) or not order_id or parsed.scheme != 'https' or parsed.hostname not in allowed_hosts:
            raise HTTPException(502, 'Square could not start secure checkout. Your registration is saved; retry from this form.')
        db.table('camp_registrations').update({
            'square_order_id': order_id, 'payment_link_url': checkout_url,
        }).eq('request_id', str(data.request_id)).execute()
        return {'checkout_url': checkout_url}
    except HTTPException:
        raise
    except APIError as exc:
        if exc.code in ('PGRST205', 'PGRST204', '42P01', '42703'):
            raise HTTPException(503, 'Camp registration needs a database update. Rerun scripts/sql/dynamic_booking_offerings.sql in Supabase.') from None
        raise HTTPException(503, 'Could not save this registration. Please retry.') from None
    except HTTPError:
        raise HTTPException(503, 'Could not reach the registration service. Please retry.') from None


def finish(db, attempt, payment):
    if (payment.get('reference_id') != attempt['id'] or payment.get('location_id') != attempt['location_id']
            or payment.get('amount_money') != {'amount': attempt['amount_cents'], 'currency': 'USD'}
            or payment.get('source_type') != 'CARD' or not payment.get('id')):
        raise HTTPException(409, 'Payment verification needs staff review. Do not pay again.')
    status = payment.get('status')
    if status in ('COMPLETED', 'FAILED', 'CANCELED'):
        return db_rpc(db, 'finish_booking_square_payment', {'p_id': attempt['id'], 'p_payment_id': payment['id'], 'p_completed': status == 'COMPLETED'})
    return {'status': 'processing'}


def process(db, settings, attempt):
    if attempt['status'] != 'processing':
        return {'status': attempt['status']}
    if attempt.get('square_order_id'):
        return process_hosted(db, settings, attempt)
    # Never replay an old unknown charge indefinitely after Square's idempotency window.
    if datetime.fromisoformat(attempt['created_at'].replace('Z','+00:00')) < datetime.now(timezone.utc) - timedelta(hours=1):
        raise HTTPException(409, 'This payment needs staff reconciliation. Do not pay again; contact the Fieldhouse.')
    code, result = square_request(settings, 'POST', '/payments', {
        'idempotency_key': attempt['id'], 'source_id': attempt['source_id'],
        'amount_money': {'amount': attempt['amount_cents'], 'currency': 'USD'},
        'location_id': attempt['location_id'], 'reference_id': attempt['id'], 'autocomplete': True,
    })
    if result.get('payment'):
        return finish(db, attempt, result['payment'])
    # Only explicit card failures release dates for a new attempt. Timeouts/unknown
    # responses retain the durable request and are retried with the SAME Square key.
    declined = {'CARD_DECLINED', 'CVV_FAILURE', 'ADDRESS_VERIFICATION_FAILURE', 'CARD_EXPIRED',
                'INSUFFICIENT_FUNDS', 'GENERIC_DECLINE', 'INVALID_CARD', 'CARD_NOT_SUPPORTED',
                'VERIFY_CVV_FAILURE', 'VERIFY_AVS_FAILURE', 'CARD_TOKEN_EXPIRED', 'INVALID_EXPIRATION'}
    errors = {e.get('code') for e in result.get('errors', [])}
    if code == 400 and errors and errors <= declined:
        return db_rpc(db, 'finish_booking_square_payment', {'p_id': attempt['id'], 'p_payment_id': None, 'p_completed': False})
    raise HTTPException(503, 'Payment status is uncertain. Use Check payment status; do not start another payment.')


def finish_hosted(db, attempt, payment):
    if (payment.get('order_id') != attempt.get('square_order_id')
            or payment.get('location_id') != attempt['location_id']
            or payment.get('amount_money') != {'amount': attempt['amount_cents'], 'currency': 'USD'}
            or not payment.get('id')):
        raise HTTPException(409, 'Payment verification needs staff review. Do not pay again.')
    if payment.get('status') == 'COMPLETED':
        return db_rpc(db, 'finish_booking_square_payment', {
            'p_id': attempt['id'], 'p_payment_id': payment['id'], 'p_completed': True})
    # A hosted link can be retried after a declined payment. Keep the dates locked
    # to this same link until Square confirms completion.
    return {'status': 'processing'}


def process_hosted(db, settings, attempt):
    code, result = square_request(settings, 'GET', '/orders/' + attempt['square_order_id'])
    order = result.get('order', {})
    if code != 200 or not order:
        raise HTTPException(503, 'Could not check hosted checkout status.')
    if (order.get('id') != attempt['square_order_id'] or order.get('location_id') != attempt['location_id']
            or order.get('reference_id') != attempt['id']
            or order.get('total_money') != {'amount': attempt['amount_cents'], 'currency': 'USD'}):
        raise HTTPException(409, 'Payment verification needs staff review. Do not pay again.')
    for tender in order.get('tenders', []):
        payment_id = tender.get('payment_id')
        if not payment_id:
            continue
        payment_code, payment_result = square_request(settings, 'GET', '/payments/' + payment_id)
        if payment_code != 200 or not payment_result.get('payment'):
            raise HTTPException(503, 'Could not check hosted checkout status.')
        outcome = finish_hosted(db, attempt, payment_result['payment'])
        if outcome.get('status') == 'completed':
            return outcome
    return {'status': 'processing'}


@router.post('/pay')
def pay(data: Charge, user=Depends(verified_customer), db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    if data.source_id.upper() in ('CASH', 'EXTERNAL'):
        raise HTTPException(422, 'Use a card through the Square payment form.')
    attempt = db_rpc(db, 'begin_booking_square_payment', {'p_id': str(data.request_id), 'p_user_id': str(user.id),
        'p_booking_ids': [str(i) for i in data.booking_ids], 'p_source': data.source_id,
        'p_location': square_credentials(settings)['location_id'], 'p_expected': data.expected_amount_cents})
    return process(db, settings, attempt)


@router.post('/reconcile')
def reconcile(user=Depends(verified_customer), db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    try:
        rows = db.table('booking_square_payments').select('*').eq('customer_user_id', str(user.id)).eq('status','processing').limit(30).execute().data
    except (APIError, httpx.HTTPError):
        raise HTTPException(503, 'Could not check payment status.') from None
    results = [process(db, settings, row) for row in rows]
    return {'processing': any(r['status'] == 'processing' for r in results), 'checked': len(results)}


@router.post('/webhook')
async def webhook(request: Request, db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
    key = square_credentials(settings)['webhook_signature_key']
    url = settings.square_webhook_url
    if not key or not url:
        raise HTTPException(503, 'Webhook is not configured.')
    raw = await request.body()
    expected = base64.b64encode(hmac.new(key.encode(), url.encode() + raw, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(expected, request.headers.get('x-square-hmacsha256-signature','')):
        raise HTTPException(403, 'Invalid signature.')
    event = await request.json()
    return await run_in_threadpool(handle_webhook, event, db, settings)


def handle_webhook(event, db, settings):
    try:
        payment_id = event.get('data',{}).get('object',{}).get('payment',{}).get('id')
        if event.get('type') not in ('payment.created','payment.updated') or not payment_id:
            return {'received': True}
        code, result = square_request(settings, 'GET', '/payments/' + payment_id)
        if code != 200 or not result.get('payment'):
            raise HTTPException(503, 'Could not verify payment.')
        payment = result['payment']
        order_id = payment.get('order_id')
        if order_id:
            rows = db.table('booking_square_payments').select('*').eq('square_order_id', order_id).execute().data
            if rows:
                finish_hosted(db, rows[0], payment)
                return {'received': True}
            registrations = db.table('camp_registrations').select('*').eq('square_order_id', order_id).limit(1).execute().data
            if registrations:
                registration = registrations[0]
                if (payment.get('order_id') != order_id
                        or payment.get('location_id') != square_credentials(settings)['location_id']
                        or payment.get('amount_money') != {'amount': registration['amount_cents'], 'currency': 'USD'}):
                    raise HTTPException(409, 'Camp payment verification needs staff review.')
                status = payment.get('status')
                updates = {'square_payment_id': payment.get('id')}
                if status == 'COMPLETED':
                    updates['status'] = 'paid'
                elif status in ('FAILED', 'CANCELED'):
                    updates['status'] = 'payment_failed'
                db.table('camp_registrations').update(updates).eq('id', registration['id']).execute()
                return {'received': True}
        try:
            attempt_id = str(UUID(payment.get('reference_id','')))
        except (ValueError, TypeError):
            return {'received': True}
        rows = db.table('booking_square_payments').select('*').eq('id', attempt_id).execute().data
        if rows:
            finish(db, rows[0], payment)
    except (APIError, httpx.HTTPError):
        raise HTTPException(503, 'Payment reconciliation unavailable.') from None
    return {'received': True}
