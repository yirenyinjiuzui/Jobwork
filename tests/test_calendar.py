from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sqlite3

from calendar_export import export_application
from tracker import parse_notice
from workbench import Store, SCHEMA, HK, prioritize

class CalendarTests(unittest.TestCase):
    def test_hong_kong_and_all_day_both(self):
        record=dict(id=4,company='范例科技',title='AI 实习',status='interview',
                    interview_reply_by='2026-12-06',interview_at='2026-12-08T14:00+08:00',
                    date_precision={'interview_reply_by':'estimated'})
        blob=export_application(record,'demo',datetime(2026,11,19,14,tzinfo=timezone.utc))
        s=blob.decode()
        self.assertIn('DTSTART:20261208T060000Z\r\n',s)
        self.assertIn('DTSTART;VALUE=DATE:20261206\r\n',s)
        self.assertIn('推算',s.replace('\r\n ',''))
        self.assertIn('未注明时刻',s.replace('\r\n ',''))
        self.assertEqual(s.count('BEGIN:VEVENT'),2)
        self.assertNotIn('DTEND',s)

    def test_interview_priorities_and_calendar_after_stage_change_and_reschedule(self):
        with TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'interviews.sqlite3')
            app=store.save_application(dict(company='Fictional Interview',title='Intern',status='submitted',deadline='2026-11-25'))
            for day in (1,2,3):
                store.save_application(dict(company='Other',title=str(day),status='saved',deadline=f'2026-12-0{day}'))
            def check(action, starts, day=27):
                top=prioritize(store.applications(),datetime(2026,11,day,9,tzinfo=HK))[0]
                self.assertEqual(top['id'],app['id'])
                self.assertIn(action,top['reason'])
                row,ns=store.calendar_row(app['id'])
                actual=export_application(row,ns).decode().splitlines()
                self.assertCountEqual([line for line in actual if line.startswith('DTSTART')],starts)
            slot='DTSTART:20261129T070000Z'
            notice=parse_notice('Interview invitation. Date/Time: 2026-11-29 15:00 HKT.','2026-11-26 09:00')
            store.import_notice(notice,id=app['id'])
            check('待参加面试',[slot])
            notice=parse_notice('Interview invitation. Please reply by 2026-11-28.','2026-11-27 09:00')
            store.import_notice(notice,id=app['id'])
            reply='DTSTART;VALUE=DATE:20261128'
            check('面试回复',[reply,slot])
            moved=parse_notice('面试改期至 2026-11-30。','2026-11-28 09:00')
            store.import_notice(moved,id=app['id'])
            check('待参加面试',[reply,'DTSTART;VALUE=DATE:20261130'],day=29)
            store.save_application(dict(id=app['id'],interview_reply_by=''))
            check('待参加面试',['DTSTART;VALUE=DATE:20261130'])

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

    def test_old_interview_deadline_requires_matching_reply_evidence(self):
        with TemporaryDirectory() as tmp:
            file=Path(tmp)/'legacy.sqlite3'
            store=Store(file)
            for title in ('Unverified','Explicit'):
                app=store.save_application(dict(company='Fictional',title=title,status='interview',deadline='2026-11-28',interview_at='2026-11-29'))
            with store.connect(True) as db:
                db.execute('ALTER TABLE applications DROP COLUMN interview_reply_by')
                db.execute("UPDATE applications SET last_notice_fingerprint='old' WHERE id=?",(app['id'],))
                db.execute("INSERT INTO history(application_id,fingerprint,created_at,received_at,status,source_url,notes,applied) VALUES (?,'old','','','interview','',?,1)",
                           (app['id'],'识别状态：interview；截止 2026-11-28；证据 粘贴通知当前正文 / text：Interview invitation. Please reply by 2026-11-28.'))
            store=Store(file)
            rows={a['title']:a for a in store.applications()}
            self.assertEqual(rows['Unverified']['deadline'],'2026-11-28')
            self.assertEqual(rows['Unverified']['interview_reply_by'],'')
            self.assertEqual(rows['Explicit']['interview_reply_by'],'2026-11-28')
            store.save_application(dict(id=app['id'],interview_reply_by=''))
            self.assertFalse(Store(file).calendar_row(app['id'])[0]['interview_reply_by'])

    def test_closed_missing_dates_no_calendar(self):
        with self.assertRaises(ValueError):
            export_application(dict(status='interview',deadline='2027-01-01'))
        with self.assertRaises(ValueError):
            export_application(dict(status='closed',interview_at='2027-01-01T12:00+08:00'))
        with self.assertRaises(ValueError):
            export_application(dict(status='assessment'))

if __name__=='__main__':
    unittest.main()
