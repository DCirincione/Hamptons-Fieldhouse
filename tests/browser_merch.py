"""Merchandise product dialog and cart browser checks."""
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app.main import app

product = {
    'id': 1, 'name': 'Fieldhouse Hoodie', 'image': 'https://images.test/black-front.png',
    'images': ['https://images.test/black-front.png', 'https://images.test/black-back.png'],
    'price_min': 42, 'price_max': 44,
    'variants': [
        {'id': 11, 'name': 'Black / S', 'color': 'Black', 'size': 'S', 'price': '42.00',
         'image': 'https://images.test/black-front.png', 'images': ['https://images.test/black-front.png', 'https://images.test/black-back.png']},
        {'id': 12, 'name': 'Black / M', 'color': 'Black', 'size': 'M', 'price': '42.00',
         'image': 'https://images.test/black-front.png', 'images': ['https://images.test/black-front.png', 'https://images.test/black-back.png']},
        {'id': 13, 'name': 'Red / M', 'color': 'Red', 'size': 'M', 'price': '44.00',
         'image': 'https://images.test/red-front.png', 'images': ['https://images.test/red-front.png']},
    ],
}

with TestClient(app) as client, sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def handle(route):
        url = urlparse(route.request.url)
        if url.hostname == 'images.test':
            return route.fulfill(status=200, content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"/>')
        if url.hostname != 'fieldhouse.test':
            return route.abort()
        if url.path == '/api/merch':
            return route.fulfill(json={'products': [product], 'checkout_enabled': False})
        response = client.get(url.path)
        return route.fulfill(status=response.status_code, body=response.content,
                             headers={'content-type': response.headers.get('content-type', '')})

    page.route('**/*', handle)
    page.goto('http://fieldhouse.test/merch')
    assert page.locator('.merch-floating-cart').is_visible()
    floating_box = page.locator('.merch-floating-cart').bounding_box()
    ada_box = page.locator('#accessibility-launcher').bounding_box()
    assert floating_box['y'] + floating_box['height'] <= ada_box['y']
    page.locator('.merch-card-open').click()
    assert page.locator('#merch-product-dialog').is_visible()
    assert page.locator('.merch-thumbnail').count() == 2
    assert page.locator('#merch-size option').count() == 2
    page.locator('#merch-color').select_option('Red')
    assert page.locator('#merch-size option').count() == 1
    assert page.locator('#merch-product-price').inner_text() == '$44.00'
    assert page.locator('#merch-product-image').get_attribute('src').endswith('/red-front.png')
    page.locator('#merch-quantity').fill('2')
    page.locator('#merch-add-to-cart').click()
    assert page.locator('#merch-cart-count').inner_text() == '2'
    assert page.locator('.merch-floating-cart .merch-cart-count').inner_text() == '2'
    page.locator('.merch-dialog-close').first.click()
    page.locator('#merch-cart-button').click()
    assert page.locator('.merch-cart-item h3').inner_text() == 'Fieldhouse Hoodie'
    assert page.locator('#merch-cart-subtotal').inner_text() == '$88.00'
    page.locator('.merch-cart-controls button').nth(1).click()
    assert page.locator('#merch-cart-count').inner_text() == '3'
    page.reload()
    assert page.locator('#merch-cart-count').inner_text() == '3'
    page.set_viewport_size({'width': 375, 'height': 667})
    page.locator('.merch-card-open').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    box = page.locator('#merch-product-dialog').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 375
    assert not errors, errors
    browser.close()

print('Merchandise browser checks passed.')
