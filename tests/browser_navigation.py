"""Focused responsive header navigation browser checks."""
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.main import app

with TestClient(app) as client, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 375, 'height': 667})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname != 'fieldhouse.test':
            return route.abort()
        if url.path.startswith('/api/'):
            return route.fulfill(status=401, json={'detail': 'Sign in'})
        response = client.get(url.path)
        return route.fulfill(status=response.status_code, body=response.content,
                             headers={'content-type': response.headers.get('content-type', '')})

    page.route('**/*', handle)
    page.goto('http://fieldhouse.test/')
    assert page.locator('.desktop-nav').is_hidden()
    assert page.locator('.mobile-nav summary').is_visible()
    page.locator('.mobile-nav summary').click()
    assert page.locator('.mobile-nav nav').is_visible()
    assert page.locator('.mobile-nav nav a').count() == 5
    page.keyboard.press('Escape')
    assert page.locator('.mobile-nav nav').is_hidden()
    assert page.locator('.mobile-nav summary').evaluate('(el) => el === document.activeElement')
    page.set_viewport_size({'width': 1000, 'height': 800})
    assert page.locator('.desktop-nav').is_visible()
    assert page.locator('.mobile-nav').is_hidden()
    assert not errors, errors
    browser.close()

print('Responsive navigation browser checks passed.')
