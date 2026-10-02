import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.main import app
from app.auth import get_auth_client
from app.routes.bookings import get_booking_db


def user(role='member', confirmed=True, metadata=None):
    return SimpleNamespace(id='account-id',email='person@example.com',email_confirmed_at='2026-10-01' if confirmed else None,
                           app_metadata={'role':role},user_metadata=metadata or {'name':'Person'})


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.auth=Mock()
        self.db=Mock()
        self.auth.auth.get_user.return_value=SimpleNamespace(user=user())
        self.session=SimpleNamespace(access_token='secret-access',refresh_token='secret-refresh',expires_in=3600)
        app.dependency_overrides[get_auth_client]=lambda:self.auth
        app.dependency_overrides[get_booking_db]=lambda:self.db
        self.client=TestClient(app)
        self.headers={'X-Fieldhouse-Request':'1'}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()

    def test_signup_cannot_set_permissions(self):
        payload={'name':'New member','email':'member@example.com','password':'a-long-password'}
        self.auth.auth.sign_up.return_value=SimpleNamespace(session=None)
        response=self.client.post('/api/auth/signup',json=payload,headers=self.headers)
        self.assertEqual(response.status_code,200)
        sent=self.auth.auth.sign_up.call_args.args[0]
        self.assertEqual(sent['options']['data'],{'name':'New member'})
        self.assertNotIn('app_metadata',sent)
        self.assertEqual(self.client.post('/api/auth/signup',json=payload|{'role':'admin'},headers=self.headers).status_code,422)

    def test_signin_uses_httponly_cookies_not_json_tokens(self):
        self.auth.auth.sign_in_with_password.return_value=SimpleNamespace(session=self.session)
        result=self.client.post('/api/auth/login',json={'email':'person@example.com','password':'pass'},headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertNotIn('secret-',result.text)
        self.assertTrue(all('HttpOnly' in c and 'SameSite=lax' in c for c in result.headers.get_list('set-cookie')))
        self.assertEqual(self.client.cookies.get('fh_access'),'secret-access')
        with TestClient(app,base_url='https://fieldhouse.example') as production:
            secure=production.post('/api/auth/login',json={'email':'person@example.com','password':'pass'},headers=self.headers)
            self.assertTrue(all('Secure' in c for c in secure.headers.get_list('set-cookie')))

    def test_member_and_user_metadata_admin_cannot_access_staff(self):
        self.client.cookies.set('fh_access','valid-session')
        for person in [user(),user(metadata={'role':'admin','is_admin':True}),user(role='admin',confirmed=False)]:
            self.auth.auth.get_user.return_value=SimpleNamespace(user=person)
            self.assertEqual(self.client.get('/admin/bookings').status_code,403)
            self.assertEqual(self.client.get('/api/bookings/staff').status_code,403)
            self.assertEqual(self.client.get('/api/bookings/staff/schedule?month=2026-10-01').status_code,403)
            self.assertEqual(self.client.post(f'/api/bookings/staff/{uuid4()}',json={'action':'approve'},headers=self.headers).status_code,403)
            self.assertFalse(self.client.get('/api/auth/me').json()['is_admin'])
        self.db.table.assert_not_called()
        self.db.rpc.assert_not_called()

    def test_admin_and_role_revocation(self):
        self.client.cookies.set('fh_access','valid-session')
        self.auth.auth.get_user.return_value=SimpleNamespace(user=user(role='admin'))
        self.assertEqual(self.client.get('/admin/bookings').status_code,200)
        self.assertTrue(self.client.get('/api/auth/me').json()['is_admin'])
        self.auth.auth.get_user.return_value=SimpleNamespace(user=user())
        self.assertEqual(self.client.get('/admin/bookings').status_code,403)
        self.auth.auth.get_user.assert_called_with('valid-session')

    def test_no_cookie_redirects_to_login_and_old_admin_token_rejected(self):
        page=self.client.get('/admin/bookings',follow_redirects=False)
        self.assertEqual(page.status_code,303)
        self.assertEqual(page.headers['location'],'/account?next=admin')
        self.assertEqual(self.client.get('/api/bookings/staff',headers={'Authorization':'Bearer old-admin-token'}).status_code,401)
        self.auth.auth.get_user.assert_not_called()

    def test_csrf_rejected_before_mutation(self):
        payload={'email':'person@example.com','password':'pass'}
        for headers in [{},self.headers|{'Origin':'https://evil.example'},self.headers|{'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual(self.client.post('/api/auth/login',json=payload,headers=headers).status_code,403)
        self.auth.auth.sign_in_with_password.assert_not_called()
        self.client.cookies.set('fh_access','valid-session')
        self.auth.auth.get_user.return_value=SimpleNamespace(user=user(role='admin'))
        self.assertEqual(self.client.post(f'/api/bookings/staff/{uuid4()}',json={'action':'approve'}).status_code,403)
        self.db.rpc.assert_not_called()

    def test_refresh_and_logout(self):
        self.client.cookies.set('fh_refresh','refresh-secret',path='/api/auth')
        self.auth.auth.refresh_session.return_value=SimpleNamespace(session=self.session)
        self.assertEqual(self.client.post('/api/auth/refresh',headers=self.headers).status_code,200)
        self.auth.auth.refresh_session.assert_called_with('refresh-secret')
        self.assertEqual(self.client.post('/api/auth/logout',headers=self.headers).status_code,200)
        self.assertIsNone(self.client.cookies.get('fh_access'))
        self.auth.auth.admin.sign_out.assert_called_once_with('secret-access',scope='local')

    def test_invalid_session_is_not_trusted(self):
        self.client.cookies.set('fh_access','forged')
        self.auth.auth.get_user.side_effect=AuthApiError('Invalid token',401,'bad_jwt')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.db.table.assert_not_called()
