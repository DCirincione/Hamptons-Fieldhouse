"""Mocked Square browser integration; never charges a card or writes live bookings."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app.main import app

catalog=json.loads((Path(__file__).resolve().parents[1]/'app/data/offerings.json').read_text())
now=datetime.now(ZoneInfo('America/New_York'))
target=(now+timedelta(days=2)).replace(hour=10,minute=0,second=0,microsecond=0)
bookings=[]; charges=[]; quotes=[]; failures=[]; errors=[]
def make_booking(day):
    return dict(id=str(uuid4()),name='Full Field',starts_at=day.isoformat(),ends_at=(day+timedelta(hours=1)).isoformat(),
                total_price_cents=20000,status='pending',payment_status='unpaid',payment_method='other',party_size=1)
bookings.append(make_booking(target))
with patch('app.main.get_rental_catalog',return_value=catalog), TestClient(app) as client, sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda error: errors.append(str(error)))
    def route_handler(route):
        request=route.request; path=urlparse(request.url).path
        if 'sandbox.web.squarecdn.com' in request.url:
            route.fulfill(content_type='application/javascript',body="window.Square={payments:()=>({card:async()=>({attach:async()=>{},destroy:async()=>{},tokenize:async()=>({status:'OK',token:'fake-card-token'})})})};")
        elif path=='/api/auth/me':
            route.fulfill(json={'email':'test@example.com','name':'Test User','phone_number':'6315550123','email_confirmed':True,'is_admin':False})
        elif path=='/api/square/config':
            route.fulfill(json={'enabled':True,'environment':'sandbox','application_id':'app','location_id':'location'})
        elif path=='/api/bookings/mine':
            route.fulfill(json={'bookings':bookings,'has_more':False})
        elif path=='/api/square/quote':
            ids=request.post_data_json['booking_ids']; quotes.append(ids)
            route.fulfill(json={'amount_cents':20000*len(ids),'currency':'USD','date_count':len(ids)})
        elif path=='/api/square/pay':
            body=request.post_data_json; charges.append(body)
            if failures:
                kind=failures.pop(0)
                route.fulfill(status=503 if kind=='unknown' else 200,json={'detail':'Check payment status'} if kind=='unknown' else {'status':'failed'})
            else:
                for booking in bookings:
                    if booking['id'] in body['booking_ids']:booking.update(status='confirmed',payment_status='paid',payment_method='square')
                route.fulfill(json={'status':'completed'})
        elif path=='/api/bookings/availability':
            route.fulfill(json={'name':'Full Field','category':'field_rental','price_cents':20000,'included_children':1,
                'own_food_discount_cents':0,'extra_child_cents':0,'extra_pizza_cents':None,'today':now.date().isoformat(),
                'last_date':(now+timedelta(days=90)).date().isoformat(),'slots':[{'starts_at':day.isoformat(),'ends_at':(day+timedelta(hours=1)).isoformat()} for day in [target,target+timedelta(days=1)]]})
        elif path=='/api/bookings' and request.method=='POST':
            body=request.post_data_json
            assert body['payment_method']=='square'
            dates=[datetime.fromisoformat(body['starts_at']),*[datetime.fromisoformat(day+'T10:00:00').replace(tzinfo=target.tzinfo) for day in body['additional_dates']]]
            bookings[:]=[make_booking(day) for day in dates]
            route.fulfill(status=201,json={'bookings':bookings,'total_price_cents':20000*len(bookings),'request_id':body['request_id']})
        elif path=='/api/square/reconcile':route.fulfill(json={'checked':0,'processing':False})
        else:
            response=client.get(path)
            route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/plain'),**({'content-security-policy':response.headers['content-security-policy']} if 'content-security-policy' in response.headers else {})})
    page.route('**/*',route_handler)
    page.goto('http://localhost/account')
    if page.locator('#privacy-notice').is_visible():page.locator('#privacy-dismiss').click()
    page.locator('.customer-booking-summary').click()
    page.get_by_role('button',name='Pay with Square',exact=True).click()
    failures.append('unknown')
    page.get_by_role('button',name='Pay $200.00',exact=True).click()
    page.locator('.square-payment-dialog').get_by_role('button',name='Check payment status',exact=True).click()
    page.get_by_text('Payment successful. The paid dates are approved.',exact=True).wait_for()
    assert charges[-1]==charges[-2], 'Unknown outcomes must reuse the identical payment request'
    assert bookings[0]['status']=='confirmed'
    page.get_by_role('button',name='Close payment').click()
    assert page.get_by_role('button',name='Pay with Square',exact=True).count()==0
    for plan in ['one_session','all_sessions']:
        page.goto('http://localhost/space-rentals')
        page.locator('[data-book-service="full-field"]').click()
        if target.month != now.month: page.locator('#next-month').click()
        page.locator('#calendar-days button:not([disabled])').first.click()
        page.locator('#booking-slots button').first.click()
        page.locator('[name=payment_method]').select_option('square')
        page.locator('#toggle-additional-dates').click()
        extra=(target+timedelta(days=1)).date().isoformat()
        if extra[:7]!=target.strftime('%Y-%m'):page.locator('#additional-next').click()
        page.locator(f'#additional-days button[data-date="{extra}"]').click()
        page.locator(f'[name=payment_plan][value={plan}]').check()
        page.locator('#reserve-button').click()
        amount='$200.00' if plan=='one_session' else '$400.00'
        page.get_by_role('button',name='Pay '+amount,exact=True).wait_for()
        if plan=='all_sessions':
            failures.append('declined')
            page.get_by_role('button',name='Pay '+amount,exact=True).click()
            page.get_by_text('The payment was declined.',exact=False).wait_for()
            assert all(b['status']=='pending' for b in bookings)
        page.get_by_role('button',name='Pay '+amount,exact=True).click()
        page.get_by_text('Payment successful. The paid dates are approved.',exact=True).wait_for()
        assert len(quotes[-1])==(1 if plan=='one_session' else 2)
        assert bookings[0]['status']=='confirmed'
        assert bookings[1]['status']==('pending' if plan=='one_session' else 'confirmed')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/fieldhouse-square-mobile.png',full_page=True)
        page.get_by_role('button',name='Close payment').click()
    assert not errors, errors
    browser.close()
print('Square browser checks passed: profile pay, uncertain outcome retry, declined card retry, first-date versus all-date approval, mobile layout.')
