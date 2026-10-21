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
staff_payment = 'unpaid'
schedule_unavailable = False
block_requests = []
schedule_blocks = []
opening_hours = {"days":[dict(weekday=n, opens="06:00", closes="23:00") for n in range(7)], "overrides":[]}
hours_requests = []
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
        global staff_state, staff_payment, signed_in
        request = route.request
        parsed = urlparse(request.url)
        if parsed.path == '/api/auth/me':
            route.fulfill(status=200 if signed_in else 401,json={'name':'Admin','email':'admin@example.com','is_admin':True,'email_confirmed':True,'phone_number':'6315550123'} if signed_in else {'detail':'Sign in'})
        elif parsed.path == '/api/auth/refresh':
            route.fulfill(status=401,json={'detail':'Sign in'})
        elif parsed.path == '/api/bookings/mine':
            route.fulfill(json={'bookings':[],'has_more':False})
        elif parsed.path == '/api/auth/logout':
            signed_in = False
            route.fulfill(json={'signed_in':False})
        elif parsed.path == '/api/bookings/staff/schedule/hours':
            if request.method == 'PUT':
                hours_requests.append(request.post_data_json)
                opening_hours['days'] = request.post_data_json['days']
            route.fulfill(json=opening_hours)
        elif parsed.path == '/api/bookings/staff/schedule/hours/date':
            body = request.post_data_json
            hours_requests.append(body)
            opening_hours['overrides'] = [day for day in opening_hours['overrides'] if day['date'] != body['date']]
            if not body['reset']: opening_hours['overrides'].append(body)
            route.fulfill(json=opening_hours)
        elif parsed.path == '/api/bookings/staff/schedule' and request.method == 'GET':
            route.fulfill(status=503 if schedule_unavailable else 200,json={'detail':'Schedule unavailable'} if schedule_unavailable else schedule_blocks)
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
            route.fulfill(json=[] if staff_state == 'cancelled' else [dict(id='test-id', status=staff_state, offerings={'name':'Full Field'}, starts_at=starts, ends_at=(target+timedelta(hours=1)).isoformat(), first_name='<script>test</script>', last_name='Customer',party_size=10,email='test@example.com',phone_number='6315550123',total_price_cents=20000,payment_method='venmo',payment_status=staff_payment,own_food=False,notes='Test note',booking_line_items=[])])
        elif parsed.path == '/api/bookings/staff/test-id':
            action = request.post_data_json['action']
            if action in ('approve','approve_paid'): staff_state = 'confirmed'
            elif action == 'cancel': staff_state = 'cancelled'
            if action in ('approve_paid','mark_paid'): staff_payment = 'paid'
            route.fulfill(json={'status':staff_state})
        elif parsed.path == '/api/bookings/availability':
            slug = parse_qs(parsed.query)['service'][0]
            offer = next(o for o in catalog if o['slug'] == slug)
            payload = dict(service=slug, name=offer['name'], category=offer['category'], price_cents=offer['price_cents'], duration_minutes=offer['duration_minutes'], included_children=offer['capacity'], own_food_discount_cents=5000 if slug=='turf-fun-party' else 6000 if offer['category']=='birthday' else 0, extra_child_cents=1700, extra_pizza_cents=2200, today=now.date().isoformat(), last_date=(now + timedelta(days=90)).date().isoformat(), slots=[dict(starts_at=dt.isoformat(), ends_at=(dt + timedelta(minutes=offer['duration_minutes'])).isoformat()) for dt in [target, target+timedelta(days=3), target+timedelta(days=4,hours=1), target+timedelta(days=32)] if dt.strftime('%Y-%m') == parse_qs(parsed.query)['month'][0][:7]])
            route.fulfill(json=payload)
        elif parsed.path == '/api/bookings' and request.method == 'POST':
            payload = request.post_data_json; requests.append(payload)
            count=1+len(payload.get('additional_dates',[]))
            route.fulfill(status=201, json=dict(request_id=payload['request_id'],occurrences=count,total_price_cents=payload['expected_total_cents']*count,bookings=[dict(reference=f'test-reference-{i}',status='pending',payment_status='unpaid',total_price_cents=payload['expected_total_cents'],starts_at=(target+timedelta(days=7*i)).isoformat(),ends_at=(target+timedelta(days=7*i,minutes=90)).isoformat()) for i in range(count)]))
        else:
            response = client.get(parsed.path)
            route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get('content-type', 'text/plain'))
    page.route('**/*', route_handler)
    page.goto('http://localhost/space-rentals')
    if page.locator('#privacy-notice').is_visible(): page.locator('#privacy-dismiss').click()
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
    assert page.locator('[name=email]').input_value() == 'admin@example.com'
    page.locator('[name=phone_number]').fill('631-555-0123')
    page.locator('[name=party_size]').fill('14')
    page.locator('[name=extra_pizzas]').fill('2')
    assert '$523.00' in page.locator('#booking-total').inner_text()
    page.locator('[name=own_food]').check()
    assert '$473.00' in page.locator('#booking-total').inner_text()
    page.locator('[name=extra_pizzas]').fill('0')
    assert '$429.00' in page.locator('#booking-total').inner_text()
    page.screenshot(path='/tmp/fieldhouse-booking-desktop.png', full_page=True)
    assert not page.locator('#additional-dates-panel').is_visible()
    page.locator('#toggle-additional-dates').click()
    assert page.locator('#toggle-additional-dates').get_attribute('aria-expanded') == 'true'
    extra = (target+timedelta(days=3)).date().isoformat()
    if extra[:7] != target.strftime('%Y-%m'):
        page.locator('#additional-next').click()
    choice = page.locator(f'#additional-days button[data-date="{extra}"]')
    choice.click()
    unavailable_date = (target+timedelta(days=4)).date().isoformat()
    if unavailable_date[:7] == extra[:7]:
        assert page.locator(f'#additional-days button[data-date="{unavailable_date}"]').is_disabled()
    assert choice.get_attribute('aria-pressed') == 'true'
    choice.click()
    assert '$429.00' in page.locator('#booking-total').inner_text()
    choice.click()
    later = (target+timedelta(days=32)).date().isoformat()
    if later[:7] != extra[:7]:
        page.locator('#additional-next').click()
    page.locator(f'#additional-days button[data-date="{later}"]').click()
    assert '$1,287.00' in page.locator('#booking-total').inner_text()
    page.locator('#selected-dates button').last.click()
    assert page.locator('#selected-dates button').count() == 1
    page.locator('#toggle-additional-dates').click()
    assert not page.locator('#additional-dates-panel').is_visible()
    assert page.locator('#selected-dates button').count() == 1
    page.locator('[name=payment_method]').select_option('cash')
    assert '$858.00' in page.locator('#booking-total').inner_text()
    assert page.locator('#booking-payment-plan').is_visible()
    assert '$429.00' in page.locator('#booking-payment-summary').inner_text()
    page.locator('[name=payment_plan][value=all_sessions]').check()
    assert '$858.00' in page.locator('#booking-payment-summary').inner_text()
    page.locator('[name=payment_plan][value=one_session]').check()
    assert 'Remaining sessions' in page.locator('#booking-payment-summary').inner_text()
    page.locator('[name=payment_plan][value=all_sessions]').check()
    page.locator('#reserve-button').click()
    page.locator('#booking-receipt').wait_for(state='visible')
    assert 'awaiting staff approval' in page.locator('#booking-receipt').inner_text()
    assert len(requests)==1 and requests[0]['expected_total_cents']==42900
    assert requests[0]['payment_method']=='cash'
    assert requests[0]['payment_plan']=='all_sessions'
    assert 'all sessions · $858.00' in page.locator('#booking-receipt').inner_text()
    assert requests[0]['additional_dates']==[extra]
    assert '2 dates' in page.locator('#booking-receipt').inner_text()
    assert not page.locator('#reservation-form').is_visible()
    page.locator('#close-booking-calendar').click()
    assert not page.locator('#booking-calendar').is_visible()
    page.set_viewport_size({'width':390, 'height':844})
    page.locator('[data-book-card="speed-agility"] h3').click()
    assert page.locator('#booking-service').input_value() == 'speed-agility'
    page.locator('#calendar-days button:not([disabled])').first.click()
    page.locator('#booking-slots button').first.click()
    assert '$75.00' in page.locator('#booking-total').inner_text()
    assert not page.locator('#booking-payment-plan').is_visible()
    assert not page.locator('#party-options').is_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert page.locator('#booking-calendar').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    assert not page.locator('#additional-dates-panel').is_visible()
    page.locator('#toggle-additional-dates').click()
    page.locator('#additional-days').scroll_into_view_if_needed()
    page.locator('#booking-calendar').screenshot(path='/tmp/fieldhouse-booking-mobile.png')
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
    page.locator('#hours-all-opens').wait_for()
    page.locator('#schedule-date').fill(target.date().isoformat())
    page.locator('#schedule-date').dispatch_event('change')
    page.locator('.staff-booking').wait_for()
    page.locator('.staff-booking summary').click()
    page.screenshot(path='/tmp/fieldhouse-admin-mobile.png', full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.screenshot(path='/tmp/fieldhouse-admin-desktop.png', full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert 'Awaiting confirmation' in page.locator('.staff-booking').inner_text()
    assert '<script>test</script>' in page.locator('.staff-booking').inner_text()
    assert page.locator('.staff-booking script').count()==0
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#availability-tab').click()
    assert page.locator('#staff-schedule').is_visible()
    assert page.locator('#staff-reservations').is_visible()
    assert page.locator('#reservations-tab').count() == 0
    assert page.locator('#schedule-calendar .calendar-pending').count() == 1
    assert page.locator('.hours-weekday[open]').count() == 0
    assert page.locator('#schedule-day').count() == 0
    page.locator('#schedule-date').fill(target.date().isoformat())
    page.locator('#schedule-date').dispatch_event('change')
    page.locator('#block-custom').click()
    page.locator('[data-part=start]').fill('10:00')
    page.locator('[data-part=end]').fill('11:00')
    page.locator('#block-form [name=title]').fill('Regular soccer team')
    page.locator('#block-save').click()
    page.wait_for_function("document.querySelector('#block-status').textContent.includes('Saved 1 date')")
    assert block_requests[-1]['mode'] == 'dates'
    assert block_requests[-1]['dates'][0]['start']=='10:00'
    page.locator('#block-close').click()
    page.locator('.booked-entry summary').wait_for()
    assert 'Booked' in page.locator('.booked-entry summary').inner_text()
    assert 'Manually blocked' not in page.locator('.booked-entry summary').inner_text()
    assert not page.locator('.booked-entry p').is_visible()
    assert page.locator('#schedule-calendar .calendar-confirmed').inner_text() == '✓'
    page.locator('.booked-entry summary').click()
    assert 'Manually blocked' in page.locator('.booked-entry p').inner_text()
    page.get_by_role('button',name='Release this time',exact=True).click()
    page.wait_for_function("document.querySelectorAll('.booked-entry').length === 0")
    assert remove_requests[-1]['scope']=='occurrence'
    page.locator('#block-custom').click()
    page.locator('#block-mode').select_option('weekly')
    page.locator('#block-first').fill(target.date().isoformat())
    page.locator('#block-last').fill((target+timedelta(days=14)).date().isoformat())
    page.locator(f'[name=weekday][value="{target.weekday()}"]').check()
    page.locator('#block-save').click()
    page.wait_for_function("document.querySelector('#block-status').textContent.includes('Saved 1 date')")
    assert block_requests[-1]['mode']=='weekly'
    assert block_requests[-1]['weekdays']==[target.weekday()]
    page.locator('#block-close').click()
    page.locator('.booked-entry summary').click()
    page.get_by_role('button',name='Remove entire series',exact=True).click()
    page.wait_for_function("document.querySelectorAll('.booked-entry').length === 0")
    assert remove_requests[-1]['scope']=='series'
    # Weekly changes, date closures, restoring weekly hours, and calendar navigation.
    page.locator('#hours-all-opens').fill('08:00')
    page.locator('#hours-all-closes').fill('20:30')
    page.locator('#hours-apply-all').click()
    page.get_by_role('button', name='Save weekly hours', exact=True).click()
    page.wait_for_function("document.querySelector('#hours-status').textContent.includes('Weekly hours saved')")
    assert all(day['opens']=='08:00' for day in hours_requests[-1]['days'])
    assert '8:00 AM–8:30 PM' in page.locator('#schedule-hours-summary').inner_text()
    row = page.locator(f'[data-weekday="{target.weekday()}"]')
    row.locator('summary').click()
    row.locator('[data-hours-opens]').fill('09:30')
    page.get_by_role('button', name='Save weekly hours', exact=True).click()
    page.wait_for_function("document.querySelector('#schedule-hours-summary').textContent.includes('9:30 AM')")
    page.locator('#date-hours-panel summary').click()
    page.locator('#date-hours-closed').check()
    page.get_by_role('button', name='Save date hours', exact=True).click()
    page.wait_for_function("document.querySelector('#schedule-hours-summary').textContent === 'Closed all day'")
    assert page.locator('#schedule-day button').count() == 0
    page.get_by_role('button', name='Use weekly hours', exact=True).click()
    page.wait_for_function("document.querySelector('#schedule-hours-summary').textContent.includes('9:30 AM')")
    page.locator('#date-hours-opens').fill('11:00')
    page.locator('#date-hours-closes').fill('15:00')
    page.get_by_role('button', name='Save date hours', exact=True).click()
    page.wait_for_function("document.querySelector('#schedule-hours-summary').textContent.includes('Custom hours')")
    assert page.locator('#schedule-day').count() == 0
    old_month = page.locator('#schedule-month').inner_text()
    page.locator('#schedule-next').click()
    page.wait_for_function("old => document.querySelector('#schedule-month').textContent !== old", arg=old_month)
    page.locator('#schedule-previous').click()
    page.wait_for_function("old => document.querySelector('#schedule-month').textContent === old", arg=old_month)
    page.locator('#schedule-calendar button').filter(has_text=str(target.day)).first.click()
    assert page.locator('#schedule-calendar [aria-pressed=true]').count() == 1
    page.locator('#staff-schedule-title').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/fieldhouse-availability-mobile.png')
    page.set_viewport_size({'width':1440,'height':1000})
    page.locator('#staff-schedule-title').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/fieldhouse-availability-desktop.png')
    page.locator('#weekly-hours-title').scroll_into_view_if_needed()
    page.screenshot(path='/tmp/fieldhouse-hours-desktop.png')
    page.set_viewport_size({'width':390,'height':844})

    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('.staff-booking summary').click()
    page.get_by_role('button',name='Confirm & mark paid',exact=True).click()
    page.wait_for_function("document.querySelector('.staff-booking summary')?.textContent.includes('Confirmed')")
    assert staff_payment == 'paid'
    assert page.get_by_role('button',name='Mark as paid',exact=True).count() == 0
    # A separate unpaid fixture exercises approval first, followed by recording payment.
    staff_state, staff_payment = 'pending', 'unpaid'
    page.locator('#staff-refresh').click()
    page.wait_for_function("document.querySelector('.staff-booking summary')?.textContent.includes('Awaiting confirmation')")
    page.locator('.staff-booking summary').click()
    page.get_by_role('button',name='Confirm booking').click()
    page.wait_for_function("document.querySelector('.staff-booking summary')?.textContent.includes('Confirmed')")
    assert page.locator('#schedule-calendar .calendar-pending').count() == 0
    assert page.locator('#schedule-calendar .calendar-confirmed').inner_text() == '✓'
    assert staff_payment == 'unpaid'
    page.locator('.staff-booking summary').click()
    page.get_by_role('button',name='Mark as paid',exact=True).click()
    page.wait_for_function("document.querySelector('.staff-booking p')?.textContent.includes('venmo · paid')")
    assert staff_payment == 'paid'
    assert page.get_by_role('button',name='Mark as paid',exact=True).count() == 0
    page.locator('.staff-booking summary').click()
    page.get_by_role('button',name='Cancel & release time').click()
    page.wait_for_function("document.querySelector('#staff-status').textContent === 'No active bookings this month.'")
    # A failed schedule read must not disable hours editing or hide the page.
    schedule_unavailable = True
    page.reload()
    page.wait_for_function("!document.querySelector('#weekly-hours-fields').disabled")
    assert page.locator('#staff-schedule').is_visible()
    page.locator('#hours-all-opens').fill('07:00')
    page.locator('#hours-apply-all').click()
    page.get_by_role('button', name='Save weekly hours', exact=True).click()
    page.wait_for_function("document.querySelector('#hours-status').textContent.includes('Weekly hours saved')")
    assert all(day['opens']=='07:00' for day in hours_requests[-1]['days'])
    page.locator('#date-hours-panel summary').click()
    page.locator('#date-hours-closed').check()
    page.get_by_role('button', name='Save date hours', exact=True).click()
    page.wait_for_function("document.querySelector('#schedule-hours-summary').textContent === 'Closed all day'")
    assert page.locator('#date-hours-closed').is_enabled()
    page.locator('#staff-logout').click()
    page.wait_for_url('**/account')
    page.locator('#login-form').wait_for(state='visible')
    assert page.locator('#profile-admin a').count()==0
    assert page.evaluate("Object.keys(localStorage).every(key => key === 'fh_privacy_notice_v1')")
    assert not errors, errors
    browser.close()
app.dependency_overrides.clear()
print('Browser checks passed: modal card/keyboard opening, Escape/backdrop/close button, focus restoration, party pricing/food discount, pending submission, mobile layout, independent service selection, unavailable state, staff approval/cancellation/sign-out, availability calendar, blocking dialog, weekly hours, date overrides and resets, no JS errors.')
