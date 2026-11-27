from pathlib import Path
from tempfile import TemporaryDirectory
from email.message import EmailMessage
import unittest
from datetime import datetime
from email.utils import format_datetime
from tracker import parse_notice,parse_eml,parse_eml_notice,match_application
from workbench import Store

BASE=dict(company='Fictional Receipt Lab',title='Test Developer',requisition='TR-1',submitted_at='2026-11-01T10:00+08:00')
TEXT='Your application for Test Developer was submitted. Thank you for applying.'
def receipt(text=TEXT,sent='2026-11-20T10:00+08:00',eml=False,identity=True):
 if not eml:return parse_notice(text,received_at=sent,**{k:BASE[k] for k in ('company','title','requisition')})
 m=EmailMessage()
 if sent:m['Date']=format_datetime(datetime.fromisoformat(sent))
 m.set_content(('Company: Fictional Receipt Lab\nRole: Test Developer\nJob ID: TR-1\n' if identity else '')+text)
 return parse_eml_notice(parse_eml(m.as_bytes()))
class ReceiptTests(unittest.TestCase):
 def test_role_names_are_not_completed_assessment_objects(self):
  for text in [TEXT,'Your application for Test was submitted.','Your application for Assessment has been completed.','Application for Assessment Engineer was completed. Thank you for applying.','测试开发岗投递成功，感谢投递。','测评开发岗位已提交。']:
   for eml in (False,True):self.assertFalse(receipt(text,eml=eml)['completion'],text)
 def test_explicit_assessment_completion_still_recognized(self):
  for text in ['Your online assessment has been successfully completed.','Your test was submitted.','You completed the online assessment.','您的在线测评已完成。']:
   self.assertTrue(receipt(text)['completion'],text)
 def test_new_old_and_duplicate_receipts_preserve_advanced_states(self):
  for status in ('assessment','interview','offer','closed'):
   for eml in (False,True):
    with self.subTest(status=status,eml=eml),TemporaryDirectory() as tmp:
     s=Store(Path(tmp)/'isolated.sqlite3');a=s.save_application({**BASE,'status':status,'deadline':'2026-12-01T10:00+08:00','interview_at':'2026-12-03T14:00+08:00','next_action':'Keep original action'})
     with s.connect(True) as db:db.execute('UPDATE applications SET last_notice_at=? WHERE id=?',('2026-11-10T10:00:00+08:00',a['id']))
     a=s.applications()[0]
     b=s.save_application({**BASE,'title':'Systems Developer','requisition':'TR-2','status':'interview'})
     for sent in ('2026-11-20T10:00+08:00','2026-11-02T10:00+08:00'):
      n=receipt(text=TEXT+(' Reference: earlier receipt.' if '11-02' in sent else ''),sent=sent,eml=eml);r=s.import_notice(n,id=a['id']);self.assertFalse(r['applied']);self.assertEqual(r['application'],a)
      self.assertTrue(s.import_notice(n,id=a['id'])['duplicate'])
     self.assertEqual(next(x for x in s.applications() if x['id']==b['id']),b)
     self.assertTrue(all(not h['applied'] for h in s.history(a['id'])))
     self.assertTrue(any('application for Test Developer' in h['notes'] for h in s.history(a['id'])))
 def test_generic_eml_is_unmatched_and_manual_review_only(self):
  with TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'isolated.sqlite3');a=s.save_application({**BASE,'status':'assessment','deadline':'2026-12-01'})
   s.save_application({**BASE,'requisition':'TR-2','status':'interview'})
   n=receipt(eml=True,identity=False);self.assertTrue(n['requires_review']);self.assertIsNone(match_application(n,s.applications())['match_id'])
   r=s.import_notice(n,id=a['id'],overrides={'review_confirmed':True});self.assertFalse(r['applied']);self.assertEqual(r['application'],a)
