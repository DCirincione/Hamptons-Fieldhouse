import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app
from app.config import Settings, get_settings
from app.routes.bookings import get_booking_db
from app.auth import get_auth_client


class BookingAPITests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.settings = Settings(_env_file=None, supabase_url='', supabase_key='',
                                 supabase_service_role_key='')
        app.dependency_overrides[get_booking_db] = lambda: self.db
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.auth = Mock()
        self.auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id='user-id', email='admin@example.com', email_confirmed_at='2026-10-01', app_metadata={'role':'admin'}, user_metadata={}))
        app.dependency_overrides[get_auth_client] = lambda: self.auth
        self.client = TestClient(app)
        self.client.cookies.set('fh_access','verified-session')
        self.client.headers['X-Fieldhouse-Request']='1'
        self.payload = dict(request_id=str(uuid4()), service='full-field',
                            starts_at='2026-10-15T10:00:00-04:00', first_name='Dan', last_name='Test',
                            email='dan@example.com', phone_number='631-555-0123', party_size=10,
                            payment_method='venmo', expected_total_cents=20000)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()

    def test_availability_returns_only_rpc_result_and_disables_cache(self):
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={'slots': []})
        result = self.client.get('/api/bookings/availability?service=full-field&month=2026-10-15')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.db.rpc.assert_called_once_with('booking_availability', {'p_slug': 'full-field', 'p_month': '2026-10-01'})

    def test_reservation_calls_atomic_rpc(self):
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={'status': 'pending', 'reference': 'test'})
        result = self.client.post('/api/bookings', json=self.payload)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()['status'], 'pending')
        self.assertEqual(self.db.rpc.call_args.args[0], 'reserve_customer_bookings')
        self.assertEqual(self.db.rpc.call_args.args[1]['p_request']['payment_method'], 'venmo')
        self.assertEqual(self.db.rpc.call_args.args[1]['p_user_id'], 'user-id')
        self.assertEqual(self.db.rpc.call_args.args[1]['p_request']['email'], 'admin@example.com')

    def test_conflict_and_price_change_are_recoverable(self):
        for code in ['23P01', 'P0002', 'P0003']:
            self.db.rpc.return_value.execute.side_effect = APIError({'code': code, 'message': 'private database message', 'details': '', 'hint': ''})
            response = self.client.post('/api/bookings', json=self.payload)
            self.assertEqual(response.status_code, 409)
            self.assertNotIn('private database', response.text)

    def test_invalid_data_never_reaches_database(self):
        for change in [dict(starts_at='2026-10-15T10:00:00'), dict(service='half-field'),
                       dict(payment_method='square'), dict(party_size=0), dict(party_size=1.2),
                       dict(email='bad'), dict(phone_number='abcdefghi'), dict(total_price_cents=1),
                       dict(extra_pizzas=21)]:
            response = self.client.post('/api/bookings', json=self.payload | change)
            self.assertEqual(response.status_code, 422, change)
        self.db.rpc.assert_not_called()

    def test_database_outage_has_no_fake_slots(self):
        self.db.rpc.return_value.execute.side_effect = APIError({'code': '55000', 'message': 'secret', 'details': '', 'hint': ''})
        response = self.client.get('/api/bookings/availability?service=full-field&month=2026-10-01')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)

    def test_staff_requires_token(self):
        self.client.cookies.clear()
        for headers in [{}, {'Authorization': 'Bearer wrong'}]:
            self.assertEqual(self.client.get('/api/bookings/staff', headers=headers).status_code, 401)
            self.assertEqual(self.client.post(f'/api/bookings/staff/{uuid4()}', json={'action': 'approve'}, headers=headers).status_code, 401)
        self.db.table.assert_not_called()
        self.db.rpc.assert_not_called()

    def test_staff_approval_uses_restricted_rpc(self):
        self.client.cookies.set('fh_access', 'verified-session')
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={'status': 'confirmed'})
        response = self.client.post(f'/api/bookings/staff/{uuid4()}', json={'action': 'approve'}, headers={'X-Fieldhouse-Request': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.rpc.call_args.args[0], 'review_booking')

    def test_my_bookings_uses_session_owner_and_no_cache(self):
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={'bookings':[], 'has_more':False})
        response = self.client.get('/api/bookings/mine?user_id=someone-else')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.db.rpc.assert_called_once_with('customer_bookings',{'p_user_id':'user-id','p_view':'upcoming','p_offset':0})

    def test_customer_needs_verified_session(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/bookings/mine').status_code,401)
        self.assertEqual(self.client.post('/api/bookings',json=self.payload).status_code,401)
        self.client.cookies.set('fh_access','valid')
        self.auth.auth.get_user.return_value.user.email_confirmed_at = None
        self.assertEqual(self.client.get('/api/bookings/mine').status_code,403)
        self.db.rpc.assert_not_called()

    def test_recurring_requests_preserve_local_time_and_limit(self):
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={})
        payload=self.payload | {'starts_at':'2026-10-25T10:00:00-04:00','payment_method':'cash','additional_dates':['2026-11-08','2026-10-28']}
        self.assertEqual(self.client.post('/api/bookings',json=payload).status_code,201)
        occurrences=self.db.rpc.call_args.args[1]['p_request']['occurrences']
        self.assertEqual(len(occurrences),3)
        self.assertEqual(occurrences[-1]['starts_at'],'2026-11-08T10:00:00-05:00')
        self.assertEqual(occurrences[1]['starts_at'],'2026-10-28T10:00:00-04:00')
        for dates in [['2026-10-25'], ['2026-10-28','2026-10-28'], ['2026-10-24'], ['2028-01-01'], ['2026-11-08'] * 30]:
            self.assertEqual(self.client.post('/api/bookings',json=payload | {'additional_dates':dates}).status_code,422)
        self.assertEqual(self.client.post('/api/bookings',json=payload | {'additional_dates':list(reversed(payload['additional_dates']))}).status_code,201)
        self.assertEqual(self.db.rpc.call_args.args[1]['p_request']['occurrences'], occurrences)
        self.assertEqual(self.client.post('/api/bookings',json=payload | {'customer_user_id':'another-user'}).status_code,422)

    def test_repeat_payment_choice_is_saved_without_marking_paid(self):
        self.db.rpc.return_value.execute.return_value = SimpleNamespace(data={})
        payload = self.payload | {'starts_at':'2026-10-25T10:00:00-04:00', 'additional_dates':['2026-10-28']}
        for plan, multiplier in [('one_session',1), ('all_sessions',2)]:
            self.assertEqual(self.client.post('/api/bookings',json=payload | {'payment_plan':plan}).status_code,201)
            saved = self.db.rpc.call_args.args[1]['p_request']
            self.assertEqual(saved['payment_plan'],plan)
            self.assertEqual(saved['initial_payment_cents'],payload['expected_total_cents'] * multiplier)
            self.assertEqual(saved['session_count'],2)
            self.assertNotIn('payment_status',saved)
        self.assertEqual(self.client.post('/api/bookings',json=payload | {'payment_plan':'free'}).status_code,422)
        self.assertEqual(self.client.post('/api/bookings',json=payload | {'initial_payment_cents':1}).status_code,422)
        self.assertEqual(self.client.post('/api/bookings',json=self.payload | {'payment_plan':'all_sessions'}).status_code,201)
        self.assertEqual(self.db.rpc.call_args.args[1]['p_request']['payment_plan'],'one_session')

    def test_customer_cancel_filters_owner_status_and_start_in_atomic_write(self):
        query = Mock()
        self.db.table.return_value = query
        for method in ['update','eq','in_','gt']:
            getattr(query,method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{'id':'booking','status':'cancelled'}])
        booking_id = str(uuid4())
        self.auth.auth.get_user.return_value.user.app_metadata = {}
        response = self.client.post(f'/api/bookings/mine/{booking_id}/cancel')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'status':'cancelled'})
        query.update.assert_called_once_with({'status':'cancelled'})
        query.eq.assert_any_call('id',booking_id)
        query.eq.assert_any_call('customer_user_id','user-id')
        query.in_.assert_called_once_with('status',['pending','confirmed'])
        self.assertEqual(query.gt.call_args.args[0],'starts_at')
        query.execute.return_value = SimpleNamespace(data=[])
        self.assertEqual(self.client.post(f'/api/bookings/mine/{booking_id}/cancel').status_code,404)
        query.execute.side_effect = APIError({'code':'55000','message':'secret','details':'','hint':''})
        response = self.client.post(f'/api/bookings/mine/{booking_id}/cancel')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('secret',response.text)
        self.client.cookies.clear()
        self.assertEqual(self.client.post(f'/api/bookings/mine/{booking_id}/cancel').status_code,401)

    def test_missing_config_fails_closed(self):
        del app.dependency_overrides[get_booking_db]
        response = self.client.post('/api/bookings', json=self.payload)
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
