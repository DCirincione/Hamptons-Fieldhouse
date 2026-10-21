import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Response

from app.routes.contact import ContactReadState, set_message_read_state, staff_messages


class ContactAdminTests(unittest.TestCase):
    def test_staff_messages_are_requested_newest_first(self):
        rows = [{'id': '1', 'first_name': 'Pat', 'last_name': 'Lee', 'created_at': '2026-10-21T12:00:00Z'}]
        db = Mock()
        query = db.table.return_value.select.return_value.order.return_value.limit.return_value
        query.execute.return_value = SimpleNamespace(data=rows)
        response = Response()

        self.assertEqual(staff_messages(response, db), rows)
        db.table.assert_called_once_with('contact_messages')
        db.table.return_value.select.return_value.order.assert_called_once_with('created_at', desc=True)
        db.table.return_value.select.return_value.order.return_value.limit.assert_called_once_with(200)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_staff_can_mark_message_read(self):
        db = Mock()
        row = {'id': '11111111-1111-1111-1111-111111111111', 'read_at': '2026-10-21T17:00:00Z'}
        query = db.table.return_value.update.return_value.eq.return_value
        query.execute.return_value = SimpleNamespace(data=[row])
        result = set_message_read_state(row['id'], ContactReadState(is_read=True), db)
        self.assertEqual(result, row)
        update = db.table.return_value.update.call_args.args[0]
        self.assertIsNotNone(update['read_at'])
        db.table.return_value.update.return_value.eq.assert_called_once_with('id', row['id'])


if __name__ == '__main__':
    unittest.main()
