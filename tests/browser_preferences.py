"""Privacy notice, accessible preferences, and opt-in map browser checks."""
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app.main import app

with TestClient(app) as client, sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != 'fieldhouse.test':
            return route.abort()
        if url.path.startswith('/api/'):
            return route.fulfill(status=401, json={'detail': 'Sign in'})
        response = client.get(url.path)
        route.fulfill(status=response.status_code, body=response.content,
                      headers={'content-type': response.headers.get('content-type', '')})
    page.route('**/*', handle)
    page.goto('http://fieldhouse.test/')
    notice = page.locator('#privacy-notice')
    assert notice.is_visible()
    page.locator('#privacy-dismiss').click()
    page.reload()
    assert notice.is_hidden()
    page.locator('[data-privacy-open]').click()
    assert notice.is_visible()
    page.locator('#privacy-dismiss').click()
    page.locator('#accessibility-launcher').click()
    assert page.locator('#accessibility-dialog').is_visible()
    for key in ['largeText', 'highContrast', 'underlineLinks', 'reduceMotion']:
        page.locator(f'[data-preference="{key}"]').check()
    page.keyboard.press('Escape')
    assert page.locator('#accessibility-launcher').evaluate('(el) => el === document.activeElement')
    page.goto('http://fieldhouse.test/privacy')
    assert page.locator('html').evaluate('(el) => el.classList.length') == 4
    page.locator('#accessibility-launcher').click()
    page.locator('#accessibility-reset').click()
    assert page.locator('html').evaluate('(el) => el.classList.length') == 0
    page.keyboard.press('Escape')
    page.goto('http://fieldhouse.test/contact')
    assert page.locator('[data-map-src]').get_attribute('src') is None
    page.locator('#load-map').click()
    assert page.locator('[data-map-src]').get_attribute('src').startswith('https://www.google.com/maps')
    for path in ['/privacy', '/accessibility', '/contact', '/']:
        page.set_viewport_size({'width': 375, 'height': 667})
        page.goto('http://fieldhouse.test' + path)
        page.locator('#accessibility-launcher').click()
        page.locator('[data-preference="largeText"]').check()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), path
        dialog = page.locator('#accessibility-dialog').bounding_box()
        assert dialog['x'] >= 0 and dialog['x'] + dialog['width'] <= 375
        page.keyboard.press('Escape')
    page.evaluate('localStorage.clear()')
    page.reload()
    assert notice.is_visible()
    initial_notice_y = notice.bounding_box()['y']
    assert initial_notice_y >= 0
    page.evaluate('scrollTo(0, 500)')
    page.wait_for_timeout(50)
    assert notice.bounding_box()['y'] < initial_notice_y
    page.add_init_script("Storage.prototype.getItem = () => { throw new Error('blocked'); }; Storage.prototype.setItem = () => { throw new Error('blocked'); };")
    page.reload()
    page.locator('#privacy-dismiss').click()
    page.locator('#accessibility-launcher').click()
    page.locator('[data-preference="largeText"]').check()
    assert 'could not save' in page.locator('#preference-status').inner_text()
    assert not errors, errors
    browser.close()
print('Privacy and accessibility browser checks passed.')
