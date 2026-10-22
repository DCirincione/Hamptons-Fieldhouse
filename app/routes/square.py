"""Square booking payments. Only verified Square completion approves dates."""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.auth import verified_customer
from app.config import Settings, get_settings
from app.routes.bookings import get_booking_db

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


def configured(settings):
    credentials = square_credentials(settings)
    return (settings.square_booking_payments_enabled and bool(credentials['access_token'])
            and bool(credentials['application_id']) and bool(credentials['location_id']))


def require_square(settings):
    if not configured(settings):
        raise HTTPException(503, 'Square checkout is not available yet.')


def square_request(settings, method, path, body=None):
    require_square(settings)
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
    credentials = square_credentials(settings)
    return {'enabled': bool(configured(settings)), 'environment': settings.square_environment,
            'application_id': credentials['application_id'] if configured(settings) else '',
            'location_id': credentials['location_id'] if configured(settings) else ''}


@router.post('/quote')
def quote(data: Dates, user=Depends(verified_customer), db=Depends(get_booking_db), settings: Settings=Depends(get_settings)):
    require_square(settings)
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
