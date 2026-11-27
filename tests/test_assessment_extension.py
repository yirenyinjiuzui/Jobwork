from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tracker import parse_eml,parse_eml_notice
from workbench import Store

FIX=Path(__file__).parent/'fixtures/core-loop'
def notice(name):return parse_eml_notice(parse_eml((FIX/(name+'.eml')).read_bytes()))
class ExtensionTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.s=Store(Path(self.temp.name)/'isolated.sqlite3')
  self.a=self.s.save_application(dict(company='Fictional Core Loop',title='Agent 应用开发实习生',requisition='AGENT-03',submitted_at='2026-11-01T10:00+08:00'))
  self.s.import_notice(notice('01-invitation'),id=self.a['id'])
 def test_same_assessment_requires_extra_confirmation(self):
  n=notice('02-extension')
  with self.assertRaisesRegex(ValueError,'明确确认'):self.s.import_notice(n,id=self.a['id'])
  r=self.s.import_notice(n,id=self.a['id'],overrides={'same_assessment_confirmed':True})
  self.assertEqual(r['application']['deadline'],'2026-11-05T10:00+08:00');self.assertEqual(r['application']['date_precision']['deadline'],'estimated')
 def test_unseen_older_extension_is_history_not_schedule(self):
  r=self.s.import_notice(notice('03-extension'),id=self.a['id'],overrides={'same_assessment_confirmed':True})
  self.assertEqual(r['application']['deadline'],'2026-11-06T10:00+08:00')
  r=self.s.import_notice(notice('02-extension'),id=self.a['id'],overrides={'same_assessment_confirmed':True})
  self.assertFalse(r['applied']);self.assertEqual(r['application']['deadline'],'2026-11-06T10:00+08:00')
  r=self.s.import_notice(notice('03-extension'),id=self.a['id'],overrides={'same_assessment_confirmed':True});self.assertTrue(r['duplicate']);self.assertEqual(len(self.s.history(self.a['id'])),3)
 def test_unknown_or_different_assessment_cannot_be_forced_by_checkbox(self):
  for name in ['04-unknown','06-different-test']:
   r=self.s.import_notice(notice(name),id=self.a['id'],overrides={'review_confirmed':True,'same_assessment_confirmed':True,'status':'assessment','deadline':'2026-12-01'})
   self.assertFalse(r['applied']);self.assertEqual(r['application']['deadline'],'2026-11-03T18:00+08:00')
 def test_missing_sender_time_and_conflicting_mime_ids_remain_review(self):
  from email import policy
  from email.parser import BytesParser
  m=BytesParser(policy=policy.default).parsebytes((FIX/'02-extension.eml').read_bytes());del m['Date']
  n=parse_eml_notice(parse_eml(m.as_bytes()));self.assertTrue(n['requires_review']);self.assertFalse(n['deadline'])
  r=self.s.import_notice(n,id=self.a['id'],overrides={'review_confirmed':True});self.assertFalse(r['applied'])
  m=BytesParser(policy=policy.default).parsebytes((FIX/'02-extension.eml').read_bytes());m.add_alternative('<p>Assessment ID: OTHER-TEST</p>',subtype='html')
  n=parse_eml_notice(parse_eml(m.as_bytes()));self.assertTrue(n['requires_review']);self.assertFalse(n['assessment_id'])
 def test_legacy_assessment_without_identity_keeps_original_deadline(self):
  with self.s.connect(True) as db:
   db.execute("DELETE FROM settings WHERE key IN (?,?)",('assessment:'+str(self.a['id']),'assessment_tasks:'+str(self.a['id'])))
  r=self.s.import_notice(notice('02-extension'),id=self.a['id'],overrides={'same_assessment_confirmed':True,'review_confirmed':True})
  self.assertFalse(r['applied']);self.assertEqual(r['application']['deadline'],'2026-11-03T18:00+08:00')
