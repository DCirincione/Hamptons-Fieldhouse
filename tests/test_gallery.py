import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import get_auth_client
from app.main import app
from app.routes.gallery import get_gallery_db


class GalleryAdminTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.auth = Mock()
        self.user = SimpleNamespace(id='admin', email='admin@example.com', email_confirmed_at='now',
                                    app_metadata={'role': 'admin'}, user_metadata={})
        self.auth.auth.get_user.return_value = SimpleNamespace(user=self.user)
        app.dependency_overrides[get_auth_client] = lambda: self.auth
        app.dependency_overrides[get_gallery_db] = lambda: self.db
        self.client = TestClient(app)
        self.client.cookies.set('fh_access', 'valid')
        self.client.headers['X-Fieldhouse-Request'] = '1'

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()

    def test_gallery_admin_requires_verified_admin(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/gallery/staff').status_code, 401)
        self.client.cookies.set('fh_access', 'valid')
        self.user.app_metadata = {}
        self.assertEqual(self.client.get('/api/gallery/staff').status_code, 403)
        self.db.table.assert_not_called()

    def test_list_gallery(self):
        row = {'id': str(uuid4()), 'image_url': '/image.jpg', 'position': 1}
        query = self.db.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.execute.return_value = SimpleNamespace(data=[row])
        response = self.client.get('/api/gallery/staff')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_upload_validates_and_stores_optimized_image(self):
        photo_id = str(uuid4())
        query = self.db.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.insert.return_value = query
        query.execute.side_effect = [SimpleNamespace(data=[{'position': 4}]),
                                     SimpleNamespace(data=[{'id': photo_id, 'position': 5}])]
        bucket = self.db.storage.from_.return_value
        bucket.get_public_url.return_value = 'https://example.supabase.co/storage/photo.jpg'
        image = base64.b64encode(b'\xff\xd8\xff' + b'image').decode()
        response = self.client.post('/api/gallery/staff', json={
            'image_data': f'data:image/jpeg;base64,{image}'})
        self.assertEqual(response.status_code, 201, response.text)
        bucket.upload.assert_called_once()
        saved = query.insert.call_args.args[0]
        self.assertEqual(saved['position'], 5)
        self.assertEqual(self.client.post('/api/gallery/staff', json={
            'image_data': 'data:image/jpeg;base64,bm90LWEtanBlZw=='
        }).status_code, 422)

    def test_reorder_gallery_uses_collision_safe_positions(self):
        first, second = str(uuid4()), str(uuid4())
        query = self.db.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.update.return_value = query
        query.eq.return_value = query
        query.execute.side_effect = [
            SimpleNamespace(data=[{'id': first}, {'id': second}]),
            SimpleNamespace(data=[]), SimpleNamespace(data=[]),
            SimpleNamespace(data=[]), SimpleNamespace(data=[]),
        ]
        response = self.client.put('/api/gallery/staff/order', json={
            'photo_ids': [second, first]
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['photo_ids'], [second, first])
        updates = [call.args[0]['position'] for call in query.update.call_args_list]
        self.assertEqual(updates, [1_000_001, 1_000_002, 1, 2])

    def test_reorder_rejects_a_stale_gallery(self):
        first, missing = str(uuid4()), str(uuid4())
        query = self.db.table.return_value
        query.select.return_value = query
        query.order.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{'id': first}])
        response = self.client.put('/api/gallery/staff/order', json={
            'photo_ids': [first, missing]
        })
        self.assertEqual(response.status_code, 409)
        query.update.assert_not_called()

    def test_delete_removes_database_row_and_uploaded_object(self):
        photo_id = str(uuid4())
        query = self.db.table.return_value
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.delete.return_value = query
        query.execute.return_value = SimpleNamespace(data=[{'storage_path': 'photo.jpg'}])
        response = self.client.delete(f'/api/gallery/staff/{photo_id}')
        self.assertEqual(response.status_code, 204)
        query.delete.assert_called_once()
        self.db.storage.from_.return_value.remove.assert_called_once_with(['photo.jpg'])


if __name__ == '__main__':
    unittest.main()
