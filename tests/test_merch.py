import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


class MerchTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_page_and_unconfigured_catalog(self):
        app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
        with TestClient(app) as client:
            page = client.get('/merch')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Fieldhouse Merch', page.text)
            self.assertIn('Checkout coming soon', page.text)
            self.assertEqual(client.get('/api/merch').status_code, 503)

    @patch('app.routes.merch._request')
    def test_catalog_normalizes_products_and_variants(self, request):
        from app.routes import merch
        merch._catalog_cache = (0, [])
        request.side_effect = [
            {'result':[{'id':2,'name':'Hoodie','thumbnail_url':'https://images.example/hoodie.jpg','is_ignored':False}]},
            {'result':{'sync_product':{'id':2,'name':'Fieldhouse Hoodie','thumbnail_url':'https://images.example/hoodie.jpg'},
                       'sync_variants':[{'id':21,'name':'Black / M','color':'Black','size':'M','retail_price':'42.00',
                                         'files':[{'type':'default','preview_url':'https://images.example/logo.png'},
                                                  {'type':'preview','preview_url':'https://images.example/hoodie-front.png'},
                                                  {'type':'preview','preview_url':'https://images.example/hoodie-back.png'}],
                                         'is_ignored':False}]}}
        ]
        settings = Settings(_env_file=None, printful_api_token='secret')
        with TestClient(app) as client:
            app.dependency_overrides[get_settings] = lambda: settings
            response = client.get('/api/merch')
        self.assertEqual(response.status_code, 200, response.text)
        product = response.json()['products'][0]
        self.assertEqual(product['name'], 'Fieldhouse Hoodie')
        self.assertEqual(product['price_min'], 42)
        self.assertEqual(product['variants'][0]['image'], 'https://images.example/hoodie-front.png')
        self.assertEqual(product['images'], ['https://images.example/hoodie-front.png', 'https://images.example/hoodie-back.png'])
        self.assertEqual(product['variants'][0]['images'], ['https://images.example/hoodie-front.png', 'https://images.example/hoodie-back.png'])
        self.assertFalse(response.json()['checkout_enabled'])
        headers = request.call_args_list[0].args[1]
        self.assertEqual(headers['Authorization'], 'Bearer secret')


if __name__ == '__main__':
    unittest.main()
