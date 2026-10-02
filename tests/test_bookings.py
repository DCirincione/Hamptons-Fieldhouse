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
        self.assertEqual(self.db.rpc.call_args.args[0], 'reserve_booking')
        self.assertEqual(self.db.rpc.call_args.args[1]['p_request']['payment_method'], 'venmo')

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

    def test_missing_config_fails_closed(self):
        del app.dependency_overrides[get_booking_db]
        response = self.client.post('/api/bookings', json=self.payload)
        self.assertEqual(response.status_code, 503)


if __name__ == '__main__':
    unittest.main()
