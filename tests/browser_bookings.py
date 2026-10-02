import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch
from types import SimpleNamespace
from app.auth import get_auth_client
from pathlib import Path
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app.main import app
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
catalog = json.loads((ROOT/'app/data/offerings.json').read_text())
now = datetime.now(ZoneInfo('America/New_York'))
target = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
starts = target.isoformat()
requests = []
errors = []
staff_state = 'pending'
block_requests = []
schedule_blocks = []
remove_requests = []
signed_in = True
auth = Mock()
auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id='admin-id',email='admin@example.com',email_confirmed_at='confirmed',app_metadata={'role':'admin'},user_metadata={'name':'Admin'}))
app.dependency_overrides[get_auth_client] = lambda: auth
with patch('app.main.get_rental_catalog', return_value=catalog), TestClient(app) as client, sync_playwright() as p:
    client.cookies.set('fh_access', 'test-session')
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_handler(route):
        from urllib.parse import urlparse, parse_qs
        global staff_state, signed_in
        request = route.request
        parsed = urlparse(request.url)
        if parsed.path == '/api/auth/me':
            route.fulfill(status=200 if signed_in else 401,json={'name':'Admin','email':'admin@example.com','is_admin':True} if signed_in else {'detail':'Sign in'})
        elif parsed.path == '/api/auth/refresh':
            route.fulfill(status=401,json={'detail':'Sign in'})
        elif parsed.path == '/api/auth/logout':
            signed_in = False
            route.fulfill(json={'signed_in':False})
        elif parsed.path == '/api/bookings/staff/schedule' and request.method == 'GET':
            route.fulfill(json=schedule_blocks)
        elif parsed.path == '/api/bookings/staff/schedule' and request.method == 'POST':
            body = request.post_data_json
            block_requests.append(body)
            schedule_blocks[:] = [dict(id='block-id',resource='field',starts_at=starts,ends_at=(target+timedelta(hours=1)).isoformat(),series_id='series-id',booking_id=None,title=body['title'],status='blocked')]
            route.fulfill(status=201,json={'occurrences':1,'series_id':'series-id'})
        elif parsed.path == '/api/bookings/staff/schedule/remove':
            remove_requests.append(request.post_data_json)
            schedule_blocks.clear()
            route.fulfill(json={'removed':1})
        elif parsed.path == '/api/bookings/staff':
            assert request.headers.get('x-fieldhouse-request') == '1'
            route.fulfill(json=[] if staff_state == 'cancelled' else [dict(id='test-id', status=staff_state, offerings={'name':'Full Field'}, starts_at=starts, ends_at=(target+timedelta(hours=1)).isoformat(), first_name='<script>test</script>', last_name='Customer',party_size=10,email='test@example.com',phone_number='6315550123',total_price_cents=20000,payment_method='venmo',payment_status='unpaid',own_food=False,notes='Test note',booking_line_items=[])])
        elif parsed.path == '/api/bookings/staff/test-id':
            staff_state = 'confirmed' if request.post_data_json['action'] == 'approve' else 'cancelled'
            route.fulfill(json={'status':staff_state})
        elif parsed.path == '/api/bookings/availability':
            slug = parse_qs(parsed.query)['service'][0]
            offer = next(o for o in catalog if o['slug'] == slug)
            payload = dict(service=slug, name=offer['name'], category=offer['category'], price_cents=offer['price_cents'], duration_minutes=offer['duration_minutes'], included_children=offer['capacity'], own_food_discount_cents=5000 if slug=='turf-fun-party' else 6000 if offer['category']=='birthday' else 0, extra_child_cents=1700, extra_pizza_cents=2200, today=now.date().isoformat(), last_date=(now + timedelta(days=90)).date().isoformat(), slots=[dict(starts_at=starts, ends_at=(target + timedelta(minutes=offer['duration_minutes'])).isoformat())])
            route.fulfill(json=payload)
        elif parsed.path == '/api/bookings' and request.method == 'POST':
            payload = request.post_data_json; requests.append(payload)
            route.fulfill(status=201, json=dict(reference='test-reference', status='pending', payment_status='unpaid', total_price_cents=payload['expected_total_cents'], starts_at=starts, ends_at=(target+timedelta(minutes=90)).isoformat()))
        else:
            response = client.get(parsed.path)
            route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type', 'text/plain'))
    page.route('**/*', route_handler)
    page.goto('http://localhost/space-rentals')
    assert not page.locator('#booking-calendar').is_visible()
    page.locator('[data-book-card="full-field"] h3').click()
    assert page.locator('#booking-calendar').is_visible()
    assert page.locator('#booking-service').input_value() == 'full-field'
    page.keyboard.press('Escape')
    assert not page.locator('#booking-calendar').is_visible()
    assert page.locator('[data-book-service="full-field"]').evaluate('(element) => element === document.activeElement')
    page.locator('[data-book-service="full-field"]').press('Enter')
    assert page.locator('#booking-calendar').is_visible()
    page.mouse.click(2, 2)
    assert not page.locator('#booking-calendar').is_visible()
    page.locator('[data-book-service="turf-fun-party"]').click()
    assert page.locator('#booking-service').input_value() == 'turf-fun-party'
    if target.month != now.month:
        page.locator('#next-month').click()
    page.locator('#calendar-days button:not([disabled])').first.click()
    page.locator('#booking-slots button').first.click()
    page.locator('[name=first_name]').fill('Dan')
    page.locator('[name=last_name]').fill('Test')
    page.locator('[name=email]').fill('dan@example.com')
    page.locator('[name=phone_number]').fill('631-555-0123')
    page.locator('[name=party_size]').fill('14')
    page.locator('[name=extra_pizzas]').fill('2')
    assert '$523.00' in page.locator('#booking-total').inner_text()
    page.locator('[name=own_food]').check()
    assert '$473.00' in page.locator('#booking-total').inner_text()
    page.locator('[name=extra_pizzas]').fill('0')
    assert '$429.00' in page.locator('#booking-total').inner_text()
    page.screenshot(path='/tmp/fieldhouse-booking-desktop.png', full_page=True)
    page.locator('#reserve-button').click()
    page.locator('#booking-receipt').wait_for(state='visible')
    assert 'awaiting staff approval' in page.locator('#booking-receipt').inner_text()
    assert len(requests)==1 and requests[0]['expected_total_cents']==42900
    assert requests[0]['payment_method']=='venmo'
    assert not page.locator('#reservation-form').is_visible()
    page.locator('#close-booking-calendar').click()
    assert not page.locator('#booking-calendar').is_visible()
    page.set_viewport_size({'width':390, 'height':844})
    page.locator('[data-book-card="speed-agility"] h3').click()
    assert page.locator('#booking-service').input_value() == 'speed-agility'
    page.locator('#calendar-days button:not([disabled])').first.click()
    page.locator('#booking-slots button').first.click()
    assert '$75.00' in page.locator('#booking-total').inner_text()
    assert not page.locator('#party-options').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert page.locator('#booking-calendar').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    page.screenshot(path='/tmp/fieldhouse-booking-mobile.png', full_page=True)
    page.unroute('**/*', route_handler)
    def unavailable(route):
        if '/api/bookings/availability' in route.request.url:
            route.fulfill(status=503,json={'detail':'Online booking is temporarily unavailable.'})
        else: route_handler(route)
    page.route('**/*', unavailable)
    page.locator('#refresh-calendar').click()
    page.wait_for_function("document.querySelector('#calendar-status').textContent.includes('temporarily unavailable')")
    assert page.locator('#calendar-days button:not([disabled])').count()==0
    assert not page.locator('#reservation-form').is_visible()
    page.goto('http://localhost/admin/bookings')
    page.locator('.staff-booking').wait_for()
    page.screenshot(path='/tmp/fieldhouse-admin-mobile.png', full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.screenshot(path='/tmp/fieldhouse-admin-desktop.png', full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert 'Pending approval' in page.locator('.staff-booking').inner_text()
    assert '<script>test</script>' in page.locator('.staff-booking').inner_text()
    assert page.locator('.staff-booking script').count()==0
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#availability-tab').click()
    assert page.locator('#staff-schedule').is_visible()
    assert not page.locator('#staff-reservations').is_visible()
    page.locator('#schedule-date').fill(target.date().isoformat())
    page.locator('#schedule-date').dispatch_event('change')
    page.get_by_role('button',name='10:00–11:00 · Open',exact=True).click()
    page.locator('#block-form [name=title]').fill('Regular soccer team')
    page.locator('#block-save').click()
    page.wait_for_function("document.querySelector('#block-status').textContent.includes('Saved 1 date')")
    assert block_requests[-1]['mode'] == 'dates'
    assert block_requests[-1]['dates'][0]['start']=='10:00'
    page.get_by_role('button',name='10:00–11:00 · Reserved',exact=True).wait_for()
    page.get_by_role('button',name='Release this time',exact=True).click()
    page.get_by_role('button',name='10:00–11:00 · Open',exact=True).wait_for()
    assert remove_requests[-1]['scope']=='occurrence'
    page.locator('#block-mode').select_option('weekly')
    page.locator('#block-first').fill(target.date().isoformat())
    page.locator('#block-last').fill((target+timedelta(days=14)).date().isoformat())
    page.locator(f'[name=weekday][value="{target.weekday()}"]').check()
    page.locator('#block-save').click()
    page.wait_for_function("document.querySelector('#block-status').textContent.includes('Saved 1 date')")
    assert block_requests[-1]['mode']=='weekly'
    assert block_requests[-1]['weekdays']==[target.weekday()]
    page.get_by_role('button',name='Remove entire series',exact=True).click()
    page.get_by_role('button',name='10:00–11:00 · Open',exact=True).wait_for()
    assert remove_requests[-1]['scope']=='series'
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('#reservations-tab').click()
    assert not page.locator('#staff-schedule').is_visible()
    assert page.locator('#staff-reservations').is_visible()
    page.get_by_role('button',name='Approve booking').click()
    page.wait_for_function("document.querySelector('.staff-booking h2')?.textContent.includes('Approved')")
    page.get_by_role('button',name='Cancel & release time').click()
    page.wait_for_function("document.querySelector('#staff-status').textContent === 'No active bookings.'")
    page.locator('#staff-logout').click()
    page.wait_for_url('**/account')
    page.locator('#login-form').wait_for(state='visible')
    assert page.locator('#profile-admin a').count()==0
    assert page.evaluate('localStorage.length')==0
    assert not errors, errors
    browser.close()
app.dependency_overrides.clear()
print('Browser checks passed: modal card/keyboard opening, Escape/backdrop/close button, focus restoration, party pricing/food discount, pending submission, mobile layout, independent service selection, unavailable state, staff approval/cancellation/sign-out, no JS errors.')
