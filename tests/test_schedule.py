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
from app.routes.schedule import ScheduleBlock, HoursUpdate, DateHours, OpeningHours


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
                      dict(mode='dates',dates=[{'date':'2026-10-02','start':'07:00','end':'05:00'}]),
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


class OpeningHoursTests(unittest.TestCase):
    def test_all_weekdays_required_and_time_validation(self):
        days = [dict(weekday=n, opens='08:30', closes='21:00') for n in range(7)]
        self.assertEqual(len(HoursUpdate(days=days).days), 7)
        for invalid in [days[:6], days[:6] + [days[0]], days[:6] + [dict(weekday=7)]]:
            with self.assertRaises(ValueError): HoursUpdate(days=invalid)
        for invalid in [dict(opens='20:00', closes='08:00'), dict(opens='08:00'), dict(opens='08:00:30', closes='20:00'), dict(opens='08:00+00:00', closes='20:00')]:
            with self.assertRaises(ValueError): OpeningHours(**invalid)
        self.assertIsNone(OpeningHours().opens)
        self.assertEqual(OpeningHours(opens='00:00', closes='23:59').closes.hour, 23)

    def test_date_override_and_reset_validation(self):
        from datetime import datetime, timedelta
        from app.routes.schedule import NY
        today = datetime.now(NY).date()
        self.assertTrue(DateHours(date=today, reset=True).reset)
        self.assertIsNone(DateHours(date=today).opens)
        for day in [today - timedelta(days=1), today + timedelta(days=366)]:
            with self.assertRaises(ValueError): DateHours(date=day)
        with self.assertRaises(ValueError): DateHours(date=today, reset=True, opens='08:00', closes='17:00')

    def test_hours_endpoints_authorization_and_payloads(self):
        db = Mock()
        db.rpc.return_value.execute.return_value.data = {'days':[], 'overrides':[]}
        auth = Mock()
        member = SimpleNamespace(app_metadata={'role':'member'}, email_confirmed_at='confirmed')
        auth.auth.get_user.return_value = SimpleNamespace(user=member)
        app.dependency_overrides[get_booking_db] = lambda: db
        app.dependency_overrides[get_auth_client] = lambda: auth
        app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
        path = '/api/bookings/staff/schedule/hours'
        headers = {'X-Fieldhouse-Request':'1'}
        days = [dict(weekday=n, opens='09:00', closes='18:00') for n in range(7)]
        try:
            with TestClient(app) as client:
                self.assertEqual(client.get(path).status_code, 401)
                self.assertEqual(client.put(path, json={'days':days}, headers=headers).status_code, 401)
                client.cookies.set('fh_access','session')
                self.assertEqual(client.get(path).status_code, 403)
                self.assertEqual(client.put(path, json={'days':days}, headers=headers).status_code, 403)
                self.assertEqual(client.put(path+'/date', json={}, headers=headers).status_code, 403)
                db.rpc.assert_not_called()
                member.app_metadata = {'role':'admin'}
                self.assertEqual(client.get(path).status_code, 200)
                self.assertEqual(client.put(path, json={'days':days}, headers=headers).status_code, 200)
                self.assertEqual(db.rpc.call_args.args[0], 'set_weekly_opening_hours')
                self.assertEqual(db.rpc.call_args.args[1]['p_days'][0]['opens'], '09:00:00')
                self.assertEqual(client.put(path,json={'days':days[:6]},headers=headers).status_code,422)
                from datetime import datetime
                from app.routes.schedule import NY
                day = datetime.now(NY).date().isoformat()
                for payload in [{'date':day}, {'date':day, 'reset':True}, {'date':day, 'opens':'07:30', 'closes':'22:00'}]:
                    response = client.put(path+'/date', json=payload, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(db.rpc.call_args.args[0], 'set_date_opening_hours')
        finally:
            app.dependency_overrides.clear()

    def test_schedule_reads_legacy_slots_without_staff_rpc_or_series_column(self):
        from fastapi import Response
        from app.routes.schedule import schedule
        query = Mock()
        for name in ['select','filter','order','range']:
            getattr(query, name).return_value = query
        db = Mock()
        db.table.return_value = query
        query.execute.return_value.data = [
            {'id':'slot-a','resource':'field','during':'["2026-10-23 10:00:00+00","2026-10-23 11:00:00+00")',
             'booking_id':None,'note':'Staff team','bookings':None},
            {'id':'slot-b','resource':'backspace','during':'["2026-10-23 12:00:00+00","2026-10-23 13:00:00+00")',
             'booking_id':'booking-id','bookings':{'status':'pending','first_name':'Test','last_name':'Member','offerings':{'name':'Training'}}},
        ]
        response = Response()
        result = schedule(month=date(2026,10,15),response=response,db=db)
        self.assertEqual(result[0]['title'], 'Staff team')
        self.assertIsNone(result[0]['series_id'])
        self.assertEqual(result[1]['status'], 'pending')
        self.assertEqual(result[1]['title'], 'Training — Test Member')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        db.rpc.assert_not_called()
        query.filter.assert_called_once_with('during','ov','["2026-10-01T00:00:00-04:00","2026-11-01T00:00:00-04:00")')

    def test_monthly_bookings_include_all_pages_with_eastern_boundaries(self):
        from fastapi import Response
        from app.routes.bookings import staff_bookings
        query = Mock()
        for name in ['select','in_','order','gte','lt','range']:
            getattr(query,name).return_value = query
        query.execute.side_effect = [SimpleNamespace(data=[{'id':str(n)} for n in range(500)]), SimpleNamespace(data=[{'id':'last'}])]
        db = Mock()
        db.table.return_value = query
        result = staff_bookings(response=Response(),month=date(2026,11,12),db=db)
        self.assertEqual(len(result),501)
        query.gte.assert_called_once_with('starts_at','2026-11-01T00:00:00-04:00')
        query.lt.assert_called_once_with('starts_at','2026-12-01T00:00:00-05:00')
        self.assertEqual([call.args for call in query.range.call_args_list], [(0,499),(500,999)])
