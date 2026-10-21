"""Staff contact-message browser checks with mocked database responses."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.auth import get_auth_client
from app.main import app

auth = Mock()
auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(
    id='admin', email='admin@example.com', email_confirmed_at='now',
    app_metadata={'role': 'admin'}, user_metadata={'name': 'Admin'}))
app.dependency_overrides[get_auth_client] = lambda: auth
message = {'id': '1', 'first_name': 'Jamie', 'last_name': 'Smith',
           'email': 'jamie@example.com', 'phone_number': '631-555-0100',
           'message': 'I would like more information about a birthday party.',
           'created_at': '2026-10-21T15:30:00Z', 'read_at': None}
read_message = {'id': '2', 'first_name': 'Taylor', 'last_name': 'Jones',
                'email': 'taylor@example.com', 'phone_number': '631-555-0110',
                'message': 'Already reviewed.', 'created_at': '2026-10-20T15:30:00Z',
                'read_at': '2026-10-20T16:00:00Z'}

try:
    with TestClient(app) as client, sync_playwright() as playwright:
        client.cookies.set('fh_access', 'valid')
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})

        def handle(route):
            path = urlparse(route.request.url).path
            if path == '/api/auth/me':
                return route.fulfill(json={'email': 'admin@example.com', 'name': 'Admin', 'is_admin': True,
                                           'email_confirmed': True, 'phone_number': ''})
            if path == '/api/contact-messages/staff': return route.fulfill(json=[message, read_message])
            if path == '/api/contact-messages/staff/1' and route.request.method == 'PATCH':
                return route.fulfill(json={**message, 'read_at': '2026-10-21T17:00:00Z'})
            if path == '/api/bookings/staff': return route.fulfill(json=[])
            if path.startswith('/api/bookings/staff/schedule'): return route.fulfill(json=[])
            if urlparse(route.request.url).hostname == 'fieldhouse.test':
                response = client.get(path)
                return route.fulfill(status=response.status_code, body=response.content,
                                     headers={'content-type': response.headers.get('content-type', '')})
            return route.abort()

        page.route('**/*', handle)
        page.goto('http://fieldhouse.test/admin/bookings')
        page.locator('#contacts-tab').click()
        page.locator('.contact-admin-card').first.wait_for()
        assert page.locator('[data-contact-filter="all"]').get_attribute('aria-pressed') == 'true'
        assert page.locator('.contact-admin-card').count() == 2
        assert not page.locator('.contact-admin-card').first.get_attribute('open')
        assert page.locator('.contact-admin-card h3').first.inner_text() == 'Jamie Smith'
        assert page.locator('.contact-message-state').first.inner_text() == 'Unread'
        page.locator('.contact-admin-heading').first.click()
        assert page.locator('.contact-admin-card').first.get_attribute('open') is not None
        assert page.locator('.contact-admin-details a').first.get_attribute('href') == 'mailto:jamie@example.com'
        assert 'birthday party' in page.locator('.contact-admin-message').first.inner_text()
        page.locator('.contact-message-state').first.get_by_text('Read').wait_for()
        page.locator('[data-contact-filter="unread"]').click()
        assert page.locator('.contact-admin-card').count() == 0
        page.locator('[data-contact-filter="read"]').click()
        assert page.locator('.contact-admin-card').count() == 2
        page.locator('#contacts-tab').click()
        assert page.locator('[data-contact-filter="all"]').get_attribute('aria-pressed') == 'true'
        browser.close()
finally:
    app.dependency_overrides.clear()

print('Contact-message admin browser checks passed.')
