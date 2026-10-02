import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from app.main import app
from app.config import Settings, get_settings
from app.routes.bookings import get_booking_db
from app.auth import get_auth_client
from app.routes.schedule import ScheduleBlock


class ScheduleTests(unittest.TestCase):
    def request(self, **kwargs):
        return ScheduleBlock(request_id=uuid4(), title='Regular team', resources=['field'], **kwargs)

    def test_weekly_crosses_dst_at_same_local_time(self):
        data = self.request(mode='weekly', start_date='2026-10-25', end_date='2026-11-08', start='18:00', end='19:30', weekdays=[6])
        result = data.occurrences(today=date(2026,10,1))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['starts_at'], '2026-10-25T18:00:00-04:00')
        self.assertEqual(result[-1]['starts_at'], '2026-11-08T18:00:00-05:00')

    def test_daily_inclusive_and_individual_times(self):
        data = self.request(mode='daily', start_date='2026-10-01', end_date='2026-10-03', start='06:00', end='23:00')
        self.assertEqual(len(data.occurrences(today=date(2026,10,1))),3)
        data = self.request(mode='dates', dates=[{'date':'2026-10-02','start':'10:15','end':'11:45'}, {'date':'2026-10-02','start':'11:45','end':'12:00'}])
        self.assertEqual(len(data.occurrences(today=date(2026,10,1))),2)

    def test_invalid_ranges(self):
        for extra in [dict(mode='weekly', start_date='2026-10-01', end_date='2026-10-03', start='06:00',end='23:00',weekdays=[]),
                      dict(mode='daily',start_date='2026-10-03',end_date='2026-10-01',start='06:00',end='23:00'),
                      dict(mode='dates',dates=[]),
                      dict(mode='dates',dates=[{'date':'2026-10-02','start':'05:00','end':'07:00'}]),
                      dict(mode='dates',dates=[{'date':'2026-10-02','start':'10:00','end':'12:00'},{'date':'2026-10-02','start':'11:00','end':'13:00'}])]:
            with self.assertRaises(ValueError): self.request(**extra).occurrences(today=date(2026,10,1))

    def test_endpoints_require_staff_and_expand_server_side(self):
        db=Mock()
        db.rpc.return_value.execute.return_value=SimpleNamespace(data={'occurrences':1})
        app.dependency_overrides[get_booking_db]=lambda: db
        app.dependency_overrides[get_settings]=lambda: Settings(_env_file=None)
        auth=Mock()
        auth.auth.get_user.return_value=SimpleNamespace(user=SimpleNamespace(app_metadata={'role':'admin'},email_confirmed_at='2026-10-01'))
        app.dependency_overrides[get_auth_client]=lambda: auth
        try:
            with TestClient(app) as client:
                for path in ['/api/bookings/staff/schedule','/api/bookings/staff/schedule/remove']:
                    self.assertEqual(client.post(path,json={}).status_code,401)
                self.assertEqual(client.get('/api/bookings/staff/schedule?month=2026-10-01').status_code,401)
                db.rpc.assert_not_called()
                from app.routes.schedule import NY
                from datetime import datetime
                payload={'request_id':str(uuid4()),'title':'Team','resources':['field'],'mode':'dates','dates':[{'date':datetime.now(NY).date().isoformat(),'start':'10:00','end':'11:00'}]}
                client.cookies.set('fh_access','verified-session')
                response=client.post('/api/bookings/staff/schedule',json=payload,headers={'X-Fieldhouse-Request':'1'})
                self.assertEqual(response.status_code,201,response.text)
                self.assertEqual(db.rpc.call_args.args[0],'add_schedule_blocks')
                self.assertIn('occurrences',db.rpc.call_args.args[1]['p_request'])
        finally: app.dependency_overrides.clear()
