"""Admin gallery browser behavior with mocked storage APIs."""
import base64
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.auth import get_auth_client
from app.main import app

auth = Mock()
auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(
    id='admin', email='admin@example.com', email_confirmed_at='now',
    app_metadata={'role': 'admin'}, user_metadata={'name': 'Admin'}))
app.dependency_overrides[get_auth_client] = lambda: auth
photo = {'id': '11111111-1111-1111-1111-111111111111', 'image_url': '/assets/photos/fieldhouse-turf.jpg',
         'storage_path': None, 'position': 1, 'created_at': '2026-10-19T00:00:00Z'}
photo_two = {'id': '22222222-2222-2222-2222-222222222222', 'image_url': '/assets/photos/A7V08705-HDR-web.jpg',
             'storage_path': None, 'position': 2, 'created_at': '2026-10-19T00:00:00Z'}
calls = []
tiny_png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')

try:
    with TestClient(app) as client, sync_playwright() as p:
        client.cookies.set('fh_access', 'valid')
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1800})
        def route_request(route):
            request, path = route.request, urlparse(route.request.url).path
            if path == '/api/auth/me':
                return route.fulfill(json={'email':'admin@example.com','name':'Admin','is_admin':True,'email_confirmed':True,'phone_number':''})
            if path == '/api/bookings/staff': return route.fulfill(json=[])
            if path.startswith('/api/bookings/staff/schedule'): return route.fulfill(json=[])
            if path == '/api/gallery/staff' and request.method == 'GET': return route.fulfill(json=[photo, photo_two])
            if path == '/api/gallery/staff' and request.method == 'POST':
                calls.append(('POST', request.post_data_json)); return route.fulfill(status=201, json=photo)
            if path == '/api/gallery/staff/order' and request.method == 'PUT':
                calls.append(('PUT', request.post_data_json)); return route.fulfill(json=request.post_data_json)
            if path.startswith('/api/gallery/staff/') and request.method == 'DELETE':
                calls.append(('DELETE', None)); return route.fulfill(status=204, body='')
            if urlparse(request.url).hostname == 'fieldhouse.test':
                response = client.get(path)
                return route.fulfill(status=response.status_code, body=response.content,
                                     headers={'content-type':response.headers.get('content-type','')})
            route.abort()
        page.route('**/*', route_request)
        page.goto('http://fieldhouse.test/admin/bookings')
        page.locator('#gallery-tab').click()
        page.locator('.gallery-admin-card').first.wait_for()
        first_before_drag = page.locator('.gallery-admin-card').first
        second_before_drag = page.locator('.gallery-admin-card').nth(1)
        handle_box = first_before_drag.locator('.gallery-drag-handle').bounding_box()
        target_box = second_before_drag.bounding_box()
        page.mouse.move(handle_box['x'] + handle_box['width'] / 2, handle_box['y'] + handle_box['height'] / 2)
        page.mouse.down()
        page.mouse.move(target_box['x'] + target_box['width'] / 2, target_box['y'] + target_box['height'] - 10, steps=8)
        page.locator('.gallery-admin-card.drop-after').wait_for()
        page.mouse.up()
        page.locator('#gallery-admin-status').get_by_text('Photo order saved').wait_for()
        assert page.locator('.gallery-admin-card').first.get_attribute('data-photo-id') == photo_two['id']
        assert page.locator('.gallery-admin-card').first.locator('.gallery-move-down').is_enabled()
        assert page.locator('.gallery-admin-card').nth(1).locator('.gallery-move-up').is_enabled()
        first_card = page.locator(f'.gallery-admin-card[data-photo-id="{photo["id"]}"]')
        page.on('dialog', lambda dialog: dialog.accept())
        first_card.locator('.gallery-remove').click()
        page.locator('#gallery-admin-status').get_by_text('Photo removed').wait_for()
        assert not page.locator('#gallery-upload-panel').get_attribute('open')
        page.locator('#gallery-upload-panel summary').click()
        page.locator('#gallery-file').set_input_files({'name':'new.png','mimeType':'image/png','buffer':tiny_png})
        page.locator('#gallery-upload-form button[type=submit]').click()
        page.wait_for_function("document.querySelector('#gallery-upload-status').textContent === 'Photo added.'")
        assert not page.locator('#gallery-upload-panel').get_attribute('open')
        assert [call[0] for call in calls] == ['PUT', 'DELETE', 'POST'], calls
        assert calls[0][1]['photo_ids'] == [photo_two['id'], photo['id']]
        assert set(calls[2][1]) == {'image_data'}
        assert calls[2][1]['image_data'].startswith('data:image/jpeg;base64,')
        browser.close()
    print('Admin gallery browser checks passed.')
finally:
    app.dependency_overrides.clear()
