from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sqlite3

from calendar_export import export_application
from workbench import Store, SCHEMA

class CalendarTests(unittest.TestCase):
    def test_hong_kong_and_all_day_both(self):
        record=dict(id=4,company='范例科技',title='AI 实习',status='interview',
                    deadline='2026-12-06',interview_at='2026-12-08T14:00+08:00',
                    date_precision={'deadline':'estimated'})
        blob=export_application(record,'demo',datetime(2026,11,19,14,tzinfo=timezone.utc))
        s=blob.decode()
        self.assertIn('DTSTART:20261208T060000Z\r\n',s)
        self.assertIn('DTSTART;VALUE=DATE:20261206\r\n',s)
        self.assertIn('推算',s.replace('\r\n ',''))
        self.assertIn('未注明时刻',s.replace('\r\n ',''))
        self.assertEqual(s.count('BEGIN:VEVENT'),2)
        self.assertNotIn('DTEND',s)

    def test_safe_escaping_and_utf8_folding(self):
        record=dict(id=1,company='实习研究公司'*40+'\r\nATTENDEE:ab,cd;ef',
                    title='Engineer',status='assessment',deadline='2027-01-04T18:00')
        b=export_application(record,'demo')
        for line in b.split(b'\r\n'):
            self.assertLessEqual(len(line),75)
            line.decode('utf-8')
        s=b.decode().replace('\r\n ','')
        self.assertIn(r'\nATTENDEE:ab\,cd\;ef',s)
        self.assertNotIn('\r\nATTENDEE:',s)
        self.assertIn('DTSTART:20270104T100000Z',s)

    def test_identity_stable_after_restart_and_reschedule(self):
        def uid(text):
            return next(x for x in text.splitlines() if x.startswith('UID:'))
        with TemporaryDirectory() as tmp:
            file=Path(tmp)/'copy.sqlite3'
            first=Store(file)
            app=first.save_application(dict(company='Example',title='Software Intern',status='interview',interview_at='2026-12-15T15:00'))
            row,ns=first.calendar_row(app['id'])
            initial=export_application(row,ns).decode()
            second=Store(file)
            second.save_application(dict(id=app['id'],interview_at='2026-12-16T17:00'))
            row,ns=second.calendar_row(app['id'])
            updated=export_application(row,ns).decode()
            self.assertEqual(uid(initial),uid(updated))
            self.assertIn('DTSTART:20261216T090000Z',updated)

    def test_v1_database_upgrades_and_preserves_existing_application(self):
        with TemporaryDirectory() as tmp:
            file=Path(tmp)/'older.sqlite3'
            with closing(sqlite3.connect(file)) as db, db:
                db.executescript(SCHEMA.replace("resume_label TEXT NOT NULL DEFAULT '',",""))
                db.execute("INSERT INTO applications (company,title,requisition,identity,location,career_type,status,deadline,interview_at,next_action,source_url,last_notice_at,last_notice_fingerprint,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            ('Legacy','Test Intern','A001','legacy|req:a001','Hong Kong','intern','submitted','','','','','','','2026-11-18','2026-11-18'))
            store=Store(file)
            saved=store.applications()[0]
            self.assertEqual((saved['requisition'],saved['resume_label']),('A001',''))
            updated=store.save_application({'id':saved['id'],'resume_label':'English v2'})
            self.assertEqual((updated['status'],updated['resume_label']),('submitted','English v2'))

    def test_closed_missing_dates_no_calendar(self):
        with self.assertRaises(ValueError):
            export_application(dict(status='closed',interview_at='2027-01-01T12:00+08:00'))
        with self.assertRaises(ValueError):
            export_application(dict(status='assessment'))

if __name__=='__main__':
    unittest.main()
