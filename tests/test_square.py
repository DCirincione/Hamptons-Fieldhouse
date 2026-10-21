import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from app.main import app
from app.config import Settings, get_settings
from app.auth import get_auth_client
from app.routes.bookings import get_booking_db
from app.routes.square import process, finish


class SquareTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, square_booking_payments_enabled=True,
            square_sandbox_access_token='private-token', square_sandbox_application_id='app-id', square_sandbox_location_id='location',
            square_sandbox_webhook_signature_key='signature-secret', square_webhook_url='https://example.com/api/square/webhook')
        self.db = Mock()
        self.auth = Mock()
        self.owner = str(uuid4())
        self.auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id=self.owner,email='test@example.com',email_confirmed_at='yes'))
        app.dependency_overrides[get_settings] = lambda:self.settings
        app.dependency_overrides[get_booking_db] = lambda:self.db
        app.dependency_overrides[get_auth_client] = lambda:self.auth
        self.client=TestClient(app)
        self.client.cookies.set('fh_access','session')
        self.client.headers['X-Fieldhouse-Request']='1'
        self.attempt={'id':str(uuid4()),'status':'processing','source_id':'card-token','amount_cents':20000,
                      'location_id':'location','created_at':datetime.now(timezone.utc).isoformat()}
        self.payment={'id':'square-payment','status':'COMPLETED','source_type':'CARD','reference_id':self.attempt['id'],
                      'location_id':'location','amount_money':{'amount':20000,'currency':'USD'}}

    def tearDown(self):
        app.dependency_overrides.clear(); self.client.close()

    def test_config_never_returns_secrets_and_production_disabled(self):
        result=self.client.get('/api/square/config')
        self.assertTrue(result.json()['enabled'])
        self.assertNotIn('private-token',result.text)
        self.assertNotIn('signature-secret',result.text)
        self.settings.square_environment='production'
        self.assertFalse(self.client.get('/api/square/config').json()['enabled'])

    def test_success_and_retries_use_durable_key_amount_and_source(self):
        self.db.rpc.return_value.execute.return_value.data={'status':'completed'}
        with patch('app.routes.square.square_request',return_value=(200,{'payment':self.payment})) as api:
            self.assertEqual(process(self.db,self.settings,self.attempt)['status'],'completed')
            self.assertEqual(api.call_args.args[3]['idempotency_key'],self.attempt['id'])
            self.assertEqual(api.call_args.args[3]['amount_money']['amount'],20000)
        self.assertEqual(self.db.rpc.call_args.args[1]['p_completed'],True)

    def test_incomplete_and_mismatched_payments_never_approve(self):
        for changes in [{'amount_money':{'amount':1,'currency':'USD'}},{'location_id':'other'},
                        {'reference_id':'other'},{'source_type':'CASH'}]:
            with self.assertRaises(Exception):finish(self.db,self.attempt,self.payment|changes)
        self.assertEqual(finish(self.db,self.attempt,self.payment|{'status':'APPROVED'}),{'status':'processing'})
        self.db.rpc.assert_not_called()

    def test_decline_releases_attempt_but_unknown_errors_do_not(self):
        with patch('app.routes.square.square_request',return_value=(400,{'errors':[{'code':'CARD_DECLINED'}]})):
            process(self.db,self.settings,self.attempt)
        self.assertFalse(self.db.rpc.call_args.args[1]['p_completed'])
        self.db.reset_mock()
        with patch('app.routes.square.square_request',return_value=(500,{'errors':[{'code':'INTERNAL_SERVER_ERROR'}]})):
            with self.assertRaises(Exception):process(self.db,self.settings,self.attempt)
        self.db.rpc.assert_not_called()

    def test_payment_requires_session_csrf_and_rejects_cash_source(self):
        body={'request_id':str(uuid4()),'booking_ids':[str(uuid4())],'source_id':'CASH','expected_amount_cents':20000}
        self.assertEqual(self.client.post('/api/square/pay',json=body).status_code,422)
        self.client.headers.pop('X-Fieldhouse-Request')
        self.assertEqual(self.client.post('/api/square/pay',json=body|{'source_id':'token'}).status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/square/pay',json=body).status_code,401)
        self.db.rpc.assert_not_called()

    def test_quote_uses_owner_and_database_price(self):
        self.db.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data=[
            {'id':'id','total_price_cents':20000,'starts_at':'2099-01-01T00:00:00Z','status':'pending','payment_status':'unpaid','square_attempt_id':None}]
        result=self.client.post('/api/square/quote',json={'booking_ids':[str(uuid4())]})
        self.assertEqual(result.json()['amount_cents'],20000)
        self.assertEqual(result.json()['billing_contact']['email'],'test@example.com')
        self.db.table.return_value.select.return_value.eq.assert_called_with('customer_user_id',self.owner)

    def test_webhook_verifies_signature_then_retrieves_payment(self):
        body=json.dumps({'type':'payment.updated','data':{'object':{'payment':{'id':'square-payment'}}}})
        self.assertEqual(self.client.post('/api/square/webhook',content=body).status_code,403)
        signature=base64.b64encode(hmac.new(b'signature-secret',(self.settings.square_webhook_url+body).encode(),hashlib.sha256).digest()).decode()
        self.db.table.return_value.select.return_value.eq.return_value.execute.return_value.data=[self.attempt]
        with patch('app.routes.square.square_request',return_value=(200,{'payment':self.payment})) as api:
            result=self.client.post('/api/square/webhook',content=body,headers={'x-square-hmacsha256-signature':signature})
        self.assertEqual(result.status_code,200)
        api.assert_called_once_with(self.settings,'GET','/payments/square-payment')
        self.assertTrue(self.db.rpc.call_args.args[1]['p_completed'])

    def test_square_reservation_stays_pending_until_payment(self):
        self.db.rpc.return_value.execute.return_value.data={'bookings':[]}
        payload=dict(request_id=str(uuid4()), service='full-field',starts_at='2099-01-01T10:00:00-05:00',
                     first_name='Test',last_name='User',email='test@example.com',phone_number='6315550123',
                     party_size=1,payment_method='square',expected_total_cents=20000)
        self.assertEqual(self.client.post('/api/bookings',json=payload).status_code,201)
        saved=self.db.rpc.call_args.args[1]['p_request']
        self.assertEqual(saved['payment_method'],'other')
        self.assertEqual(saved['requested_payment_method'],'square')
        self.assertNotIn('status',saved)
