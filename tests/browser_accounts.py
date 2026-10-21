"""Browser-only account behavior; Supabase calls are mocked, no email is sent."""
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app.main import app

state = {'signed_in':False,'admin':False,'refreshes':0,'booking_status':'pending','name':'Member','phone_number':'6315550123'}
errors=[]
with TestClient(app) as client, sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.clock.install()
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        request=route.request
        path=urlparse(request.url).path
        if path=='/api/auth/me':
            route.fulfill(status=200 if state['signed_in'] else 401,json={'email':'member@example.com','name':state['name'],'is_admin':state['admin'],'email_confirmed':True,'phone_number':state['phone_number']} if state['signed_in'] else {'detail':'Sign in'})
        elif path=='/api/auth/profile':
            body=request.post_data_json
            assert set(body)=={'name','phone_number'}
            state.update(body)
            route.fulfill(json={'email':'member@example.com','name':state['name'],'phone_number':state['phone_number'],'is_admin':state['admin'],'email_confirmed':True})
        elif path=='/api/bookings/mine':
            history=parse_qs(urlparse(request.url).query).get('view')==['history']
            show=history == (state['booking_status']=='cancelled')
            start=datetime.now(timezone.utc)+timedelta(days=2)
            booking=dict(id='my-private-booking',name='Full Field',starts_at=start.isoformat(),ends_at=(start+timedelta(hours=1)).isoformat(),status=state['booking_status'],payment_status='unpaid',payment_method='cash',total_price_cents=20000,party_size=10,own_food=False,extras=[],recurring=True,request_id='my-series')
            route.fulfill(json={'bookings':[booking] if show else [],'has_more':False})
        elif path=='/api/bookings/mine/my-private-booking/cancel':
            assert request.method=='POST'
            assert request.headers['x-fieldhouse-request']=='1'
            state['booking_status']='cancelled'
            route.fulfill(json={'status':'cancelled'})
        elif path=='/api/auth/refresh':
            state['refreshes']+=1
            route.fulfill(status=401,json={'detail':'Sign in'})
        elif path=='/api/auth/signup':
            assert request.headers['x-fieldhouse-request']=='1'
            assert set(request.post_data_json)=={'name','email','password','phone_number'}
            route.fulfill(json={'signed_in':False,'message':'Check your email to confirm your account.'})
        elif path=='/api/auth/login':
            state['signed_in']=True
            route.fulfill(json={'signed_in':True})
        elif path=='/api/auth/logout':
            state['signed_in']=False
            route.fulfill(json={'signed_in':False})
        else:
            response=client.get(path)
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/plain'))
    page.route('**/*',handler)
    page.goto('http://localhost/account')
    page.locator('#login-form').wait_for(state='visible')
    assert page.locator('#profile-admin a').count()==0
    page.locator('[data-auth-mode=signup]').click()
    page.locator('#signup-form [name=name]').fill('Member')
    page.locator('#signup-form [name=email]').fill('member@example.com')
    page.locator('#signup-form [name=password]').fill('test-long-password')
    page.locator('#signup-form button[type=submit]').click()
    page.wait_for_function("document.querySelector('#account-status').textContent.includes('Check your email')")
    page.locator('[data-auth-mode=login]').click()
    page.locator('#login-form [name=email]').fill('member@example.com')
    page.locator('#login-form [name=password]').fill('test-long-password')
    page.locator('#login-form button[type=submit]').click()
    page.locator('#account-summary').wait_for(state='visible')
    page.locator('.customer-booking-summary').wait_for()
    assert not page.locator('.customer-booking').evaluate('(element) => element.open')
    assert not page.get_by_role('button',name='Cancel booking',exact=True).is_visible()
    page.locator('.customer-booking-summary').click()
    page.get_by_text('Pending approval',exact=True).wait_for()
    state['booking_status']='confirmed'
    page.clock.fast_forward(20000)
    page.get_by_text('Approved',exact=True).wait_for()
    page.locator('#customer-profile-form [name=name]').fill('Updated Member')
    page.locator('#customer-profile-form [name=phone_number]').fill('6315554567')
    page.locator('#customer-profile-form button').click()
    page.wait_for_function("document.querySelector('#customer-profile-status').textContent==='Profile saved.'")
    assert state['name']=='Updated Member'
    page.once('dialog',lambda dialog:dialog.dismiss())
    page.get_by_role('button',name='Cancel booking',exact=True).click()
    assert state['booking_status']=='confirmed'
    page.once('dialog',lambda dialog:dialog.accept())
    page.get_by_role('button',name='Cancel booking',exact=True).click()
    page.wait_for_function("document.querySelector('#my-bookings-status').textContent.includes('Booking cancelled')")
    page.locator('[data-booking-view=history]').click()
    page.locator('.customer-booking-summary').click()
    page.get_by_text('Cancelled',exact=True).wait_for()
    assert page.get_by_role('button',name='Cancel booking',exact=True).count()==0
    page.locator('#profile-dropdown summary').click()
    assert page.locator('#profile-admin a').count()==0
    assert page.locator('#profile-member').is_visible()
    page.keyboard.press('Escape')
    assert not page.locator('#profile-dropdown').evaluate('(el)=>el.open')
    state['admin']=True
    page.reload()
    page.locator('#profile-dropdown summary').click()
    page.locator('#profile-admin a').wait_for(state='visible')
    assert page.locator('#profile-admin a').get_attribute('href')=='/admin/bookings'
    page.screenshot(path='/tmp/fieldhouse-account-desktop.png',full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    box=page.locator('.profile-panel').bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=390
    page.screenshot(path='/tmp/fieldhouse-account-mobile.png',full_page=True)
    page.locator('#profile-member [data-account-signout]').click()
    page.locator('#login-form').wait_for(state='visible')
    assert page.locator('#profile-admin a').count()==0
    assert page.evaluate('localStorage.length')==0
    assert not errors, errors
    browser.close()
print('Customer portal browser checks passed: profile editing, automatic approval updates, booking history, signup, confirmation notice, login, member/admin dropdown visibility, logout, desktop/mobile layout.')
