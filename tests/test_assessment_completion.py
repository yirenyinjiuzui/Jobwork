from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tracker import parse_eml,parse_eml_notice,parse_notice
from workbench import Store

BASE=dict(company='Fictional Receipts',title='Test Intern',requisition='RC-1',submitted_at='2026-11-01T10:00+08:00')
def mail(task='A-1',day=2,complete=False,extra='',relative=False,identity=True):
 m=EmailMessage();m['Date']=f'{day:02} Nov 2026 10:00:00 +0800'
 body=('Company: Fictional Receipts\nRole: Test Intern\nJob ID: RC-1\n' if identity else '')
 body+=('Assessment ID: '+task+'\n') if task else ''
 body+=('Your online assessment has been successfully completed.' if complete else 'Online assessment. Please complete within another 48 hours.' if relative else f'Online assessment. Deadline: 2026-11-{10 if task=="A-1" else 12} 10:00 HKT.')
 m.set_content(body+'\n'+extra)
 return parse_eml_notice(parse_eml(m.as_bytes()))
class CompletionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=Store(Path(self.tmp.name)/'isolated.sqlite3');self.a=self.s.save_application(BASE)
 def apply(self,n,**overrides):return self.s.import_notice(n,id=self.a['id'],overrides=overrides)
 def test_unique_completion_only_after_confirmation_and_retains_evidence(self):
  self.apply(mail());self.apply(mail(day=3,relative=True),same_assessment_confirmed=True)
  n=mail(day=4,complete=True)
  with self.assertRaisesRegex(ValueError,'明确确认'):self.apply(n)
  r=self.apply(n,assessment_completion_confirmed=True);self.assertEqual(r['application']['status'],'waiting');self.assertEqual(r['application']['deadline'],'')
  self.assertEqual(len(self.s.history(self.a['id'])),3);self.assertTrue(self.s.state()['applications'][0]['assessment_tasks'][0]['completed'])
 def test_two_independent_tasks_complete_only_one(self):
  self.apply(mail());self.apply(mail(task='B-2',day=3));r=self.apply(mail(day=4,complete=True),assessment_completion_confirmed=True)
  self.assertEqual(r['application']['status'],'assessment');self.assertEqual(r['application']['deadline'],'2026-11-12T10:00+08:00')
  tasks={t['id']:t for t in self.s.state()['applications'][0]['assessment_tasks']};self.assertTrue(tasks['A-1']['completed']);self.assertFalse(tasks['B-2']['completed'])
  r=self.apply(mail(task='B-2',day=5,complete=True),assessment_completion_confirmed=True);self.assertEqual(r['application']['status'],'waiting');self.assertFalse(r['application']['deadline'])
 def test_duplicate_and_old_or_new_extension_never_reopen_completed(self):
  self.apply(mail());n=mail(day=4,complete=True);self.apply(n,assessment_completion_confirmed=True)
  self.assertTrue(self.apply(n,assessment_completion_confirmed=True)['duplicate'])
  for day in (3,5):
   r=self.apply(mail(day=day,relative=True),same_assessment_confirmed=True);self.assertFalse(r['applied']);self.assertEqual(r['application']['status'],'waiting');self.assertFalse(r['application']['deadline'])
 def test_generic_receipt_cannot_clear_any_task_even_with_review(self):
  self.apply(mail());self.apply(mail(task='B-2',day=3))
  n=mail(task='',day=4,complete=True,identity=False);self.assertTrue(n['requires_review'])
  r=self.apply(n,review_confirmed=True,assessment_completion_confirmed=True,status='waiting');self.assertFalse(r['applied'])
  self.assertTrue(all(not t['completed'] for t in self.s.state()['applications'][0]['assessment_tasks']))
 def test_completion_clock_is_per_task_not_other_task(self):
  self.apply(mail());self.apply(mail(task='B-2',day=6));r=self.apply(mail(day=4,complete=True),assessment_completion_confirmed=True)
  self.assertTrue(r['applied']);self.assertEqual(r['application']['deadline'],'2026-11-12T10:00+08:00');self.assertIn('11-06',r['application']['last_notice_at'])
 def test_conditional_interview_does_not_turn_receipt_into_invitation(self):
  for extra in ['If successful, we will invite you to interview.','如果通过，我们将邀请您面试。']:
   n=mail(day=4,complete=True,extra=extra);self.assertEqual(n['status'],'waiting');self.assertTrue(n['completion']);self.assertFalse(n['interview_at']);self.assertFalse(n['requires_review'])

 def test_known_completion_does_not_regress_later_interview(self):
  self.apply(mail());current=self.s.applications()[0];self.s.save_application({**current,'status':'interview','interview_at':'2026-11-15T10:00+08:00'})
  r=self.apply(mail(day=4,complete=True),assessment_completion_confirmed=True)
  self.assertTrue(r['applied']);self.assertEqual(r['application']['status'],'interview');self.assertEqual(r['application']['interview_at'],'2026-11-15T10:00+08:00')
  self.assertTrue(self.s.state()['applications'][0]['assessment_tasks'][0]['completed'])

 def test_generic_third_party_receipt_with_multiple_applications_stays_manual(self):
  from tracker import match_application
  self.apply(mail());other=self.s.save_application({**BASE,'requisition':'RC-2'})
  n=mail(task='',day=4,complete=True,identity=False)
  self.assertIsNone(match_application(n,self.s.applications())['match_id'])
  r=self.apply(n,review_confirmed=True,assessment_completion_confirmed=True)
  self.assertFalse(r['applied']);self.assertEqual(next(a for a in self.s.applications() if a['id']==other['id']),other)
 def test_receipt_with_equal_invitation_timestamp_is_only_history(self):
  self.apply(mail());r=self.apply(mail(day=2,complete=True),assessment_completion_confirmed=True)
  self.assertFalse(r['applied']);self.assertEqual(r['application']['status'],'assessment')

 def test_pasted_completion_keeps_other_assessment_on_dashboard(self):
  self.apply(mail());self.apply(mail(task='B-2',day=3))
  body='Company: Fictional Receipts\nRole: Test Intern\nJob ID: RC-1\nAssessment ID: A-1\nYour online assessment has been successfully completed.'
  old=parse_notice(body,'2026-11-02T10:00+08:00')
  self.assertFalse(self.apply(old,assessment_completion_confirmed=True)['applied'])
  receipt=parse_notice(body,'2026-11-04T10:00+08:00')
  with self.assertRaisesRegex(ValueError,'明确确认'):self.apply(receipt)
  self.assertTrue(self.apply(receipt,assessment_completion_confirmed=True)['applied'])
  state=self.s.state()
  self.assertEqual([(r['status'],r['deadline']) for r in state['today']],[('assessment','2026-11-12T10:00+08:00')])
  self.assertEqual({t['id']:t['completed'] for t in state['applications'][0]['assessment_tasks']},{'A-1':True,'B-2':False})
  self.assertTrue(self.apply(receipt,assessment_completion_confirmed=True)['duplicate'])
  self.assertEqual(len(self.s.history(self.a['id'])),4)

 def test_unverified_pasted_receipts_only_add_history(self):
  self.apply(mail());self.apply(mail(task='B-2',day=3))
  before=self.s.state()
  for label,sent in [('', '2026-11-04T10:00+08:00'),('Assessment ID: UNKNOWN','2026-11-04T10:00+08:00'),
                     ('Assessment ID: A-1\nTest ID: B-2','2026-11-04T10:00+08:00'),('Assessment ID: A-1',''),
                     ('-----原始邮件-----\nAssessment ID: B-2','2026-11-04T10:00+08:00')]:
   with self.subTest(label=label,sent=sent):
    receipt=parse_notice(f'Your online assessment has been successfully completed.\n{label}',sent,company=BASE['company'],requisition=BASE['requisition'])
    self.assertFalse(self.apply(receipt,review_confirmed=True,assessment_completion_confirmed=True,status='waiting')['applied'])
    self.assertEqual(self.s.state(),before)
    self.assertFalse(self.s.history(self.a['id'])[0]['applied'])

 def test_pasted_invitations_track_only_explicit_unambiguous_assessment_ids(self):
  identity=dict(company=BASE['company'],requisition=BASE['requisition'])
  for label in ('','Assessment ID: A-1\nTest ID: B-2'):
   notice=parse_notice(f'Online assessment. Deadline: 2026-11-10 10:00 HKT.\n{label}','2026-11-02T10:00+08:00',**identity)
   self.assertTrue(self.apply(notice)['applied'])
   self.assertEqual(self.s.applications()[0]['deadline'],'2026-11-10T10:00+08:00')
   self.assertNotIn('assessment_tasks',self.s.state()['applications'][0])
  for task,day in [('A-1',10),('B-2',12)]:
   notice=parse_notice(f'Assessment ID: {task}\nOnline assessment. Deadline: 2026-11-{day} 10:00 HKT.','2026-11-03T10:00+08:00',**identity)
   self.assertTrue(self.apply(notice)['applied'])
  receipt=parse_notice('Assessment ID: A-1\nYour online assessment has been successfully completed.','2026-11-04T10:00+08:00',**identity)
  self.assertTrue(self.apply(receipt,assessment_completion_confirmed=True)['applied'])
  pending=self.s.state()['today'][0]
  self.assertEqual({t['id']:t['completed'] for t in pending['assessment_tasks']},{'A-1':True,'B-2':False})
  self.assertEqual(pending['deadline'],'2026-11-12T10:00+08:00')
