from email.message import EmailMessage
from pathlib import Path
import tempfile,unittest
from tracker import parse_eml,parse_eml_notice,match_application,application_chronology
from workbench import Store

BASE=dict(company='Fictional Timing Lab',title='Test Developer',requisition='TIME-1')
def notice(sent='Tue, 10 Nov 2026 10:00:00 +0800',event='2026-12-02 14:00 HKT',word='Interview invitation'):
 m=EmailMessage();m['Subject']='Fictional notification'
 if sent:m['Date']=sent
 m.set_content('Company: Fictional Timing Lab\nRole: Test Developer\nJob ID: TIME-1\n'+word+'\nDate/Time: '+event)
 return parse_eml_notice(parse_eml(m.as_bytes()))

class ChronologyTests(unittest.TestCase):
 def test_later_application_and_matching_id_do_not_override_conflict(self):
  n=notice();app={**BASE,'id':1,'submitted_at':'2026-11-11T09:00+08:00'}
  self.assertEqual(application_chronology(n,app),'conflict');r=match_application(n,[app]);self.assertIsNone(r['match_id']);self.assertEqual(r['matches'],[1]);self.assertTrue(r['ambiguous'])
 def test_unknown_dates_or_same_day_only_need_review(self):
  for value in ('','2026-11-10','not-known'):
   self.assertIsNone(match_application(notice(),[{**BASE,'id':1,'submitted_at':value}])['match_id'])
  self.assertIsNone(match_application(notice(sent=''),[{**BASE,'id':1,'submitted_at':'2026-11-01'}])['match_id'])
 def test_late_entry_and_future_event_are_not_submission(self):
  app={**BASE,'id':1,'created_at':'2026-11-20T10:00+08:00','interview_at':'2026-12-05T10:00+08:00','submitted_at':'2026-11-01T10:00+08:00'}
  self.assertEqual(match_application(notice(),[app])['match_id'],1)
  app['submitted_at']='';self.assertIsNone(match_application(notice(),[app])['match_id'])
 def test_timezone_comparison_crosses_calendar_boundary(self):
  n=notice(sent='Tue, 10 Nov 2026 23:30:00 -0500')
  self.assertEqual(application_chronology(n,{'submitted_at':'2026-11-11T12:00+08:00'}),'ok')
  self.assertEqual(application_chronology(n,{'submitted_at':'2026-11-11T13:00+08:00'}),'conflict')
 def test_header_without_timezone_is_unknown(self):
  n=notice(sent='Tue, 10 Nov 2026 10:00:00 -0000')
  self.assertFalse(n['received_at'])
 def test_similar_different_role_not_matched_and_candidates_retained(self):
  n=notice();n['requisition']=''
  self.assertIsNone(match_application(n,[{**BASE,'id':1,'title':'Test Development Intern','submitted_at':'2026-11-11'}])['match_id'])
 def test_reorder_reschedule_reminder_history_and_review_only(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(Path(td)/'isolated.sqlite3');a=s.save_application({**BASE,'submitted_at':'2026-11-01T10:00+08:00'})
   new=notice(sent='Wed, 11 Nov 2026 10:00:00 +0800',event='2026-12-05 14:00 HKT',word='Interview rescheduled')
   s.import_notice(new,id=a['id']);r=s.import_notice(notice(),id=a['id']);self.assertFalse(r['applied']);self.assertIn('12-05',r['application']['interview_at'])
   reminder=notice(sent='Thu, 12 Nov 2026 10:00:00 +0800',event='2026-12-02 14:00 HKT')
   r=s.import_notice(reminder,id=a['id']);self.assertFalse(r['applied']);self.assertIn('12-05',r['application']['interview_at'])
   earlier=notice(sent='Fri, 13 Nov 2026 10:00:00 +0800',event='2026-12-03 14:00 HKT',word='Interview rescheduled')
   r=s.import_notice(earlier,id=a['id']);self.assertTrue(r['applied']);self.assertIn('12-03',r['application']['interview_at'])
   self.assertEqual(len(s.history(a['id'])),4)

 def test_same_message_idempotence_and_legacy_history_fingerprint(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(Path(td)/'test.sqlite3');a=s.save_application({**BASE,'submitted_at':'2026-11-01T10:00+08:00'})
   n=notice();s.import_notice(n,id=a['id'])
   with s.connect(True) as db:
    db.execute('UPDATE history SET fingerprint=? WHERE application_id=?',(n['legacy_fingerprint'],a['id']))
   result=s.import_notice(n,id=a['id']);self.assertTrue(result['duplicate']);self.assertEqual(len(s.history(a['id'])),1)
