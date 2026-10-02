"""Browser-only account behavior; Supabase calls are mocked, no email is sent."""
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app.main import app

state = {'signed_in':False,'admin':False,'refreshes':0}
errors=[]
with TestClient(app) as client, sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        request=route.request
        path=urlparse(request.url).path
        if path=='/api/auth/me':
            route.fulfill(status=200 if state['signed_in'] else 401,json={'email':'member@example.com','name':'Member','is_admin':state['admin']} if state['signed_in'] else {'detail':'Sign in'})
        elif path=='/api/auth/refresh':
            state['refreshes']+=1
            route.fulfill(status=401,json={'detail':'Sign in'})
        elif path=='/api/auth/signup':
            assert request.headers['x-fieldhouse-request']=='1'
            assert set(request.post_data_json)=={'name','email','password'}
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
print('Account browser checks passed: signup, confirmation notice, login, member/admin dropdown visibility, logout, desktop/mobile layout.')
