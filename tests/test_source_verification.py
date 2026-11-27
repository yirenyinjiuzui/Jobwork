from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json,threading,unittest
from discovery import manual_job,DiscoveryError,fetch_jobs
from workbench import Store

class VerificationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=Store(Path(self.tmp.name)/'isolated.sqlite3')
  self.src=self.s.save_source(dict(provider='greenhouse',board='fictionalsource',company='Fictional Source'))
  self.a=manual_job(dict(company='Fictional Source',title='Data Intern',requisition='A-1',url='https://example.invalid/jobs/A'));self.a['source_id']='greenhouse:fictionalsource:A'
  self.b={**self.a,'source_id':'greenhouse:fictionalsource:B','requisition':'B-2','url':'https://example.invalid/jobs/B'}
 def check(self,rows):
  with patch('discovery.fetch_jobs',return_value=rows):return self.s.check_sources(self.src['id'])[0]
 def jobs(self):return self.s.state()['jobs']
 def test_empty_anomaly_keeps_last_state_and_application(self):
  self.check([self.a]);job=self.jobs()[0];app=self.s.save_job_as_application(job['id']);r=self.check([])
  self.assertEqual(r['closed'],0);self.assertEqual(r['unverified'],1);self.assertTrue(self.jobs()[0]['active']);self.assertTrue(self.jobs()[0]['source_verification']['uncertain'])
  self.assertEqual(self.s.applications()[0],app);self.assertEqual(self.s.state()['notifications'],[])
  r=self.check([self.a]);self.assertEqual(r['reopened'],0);self.assertFalse(self.jobs()[0]['source_verification']['uncertain'])
 def test_first_empty_is_unknown_not_confirmed_no_hiring(self):
  self.check([]);self.assertFalse(self.s.state()['sources'][0]['initialized']);self.assertIn('暂不可核实',self.s.state()['sources'][0]['last_error'])
  self.assertTrue(self.check([self.a])['baseline'])
 def test_timeout_request_and_parse_failure_preserve_jobs(self):
  self.check([self.a]);original=self.jobs()[0]['id']
  for error in [TimeoutError('synthetic timeout'),DiscoveryError('synthetic HTTP 500'),DiscoveryError('invalid JSON')]:
   with patch('discovery.fetch_jobs',side_effect=error):r=self.s.check_sources(self.src['id'])[0]
   self.assertIn('error',r);self.assertTrue(self.jobs()[0]['active']);self.assertEqual(self.jobs()[0]['id'],original);self.assertTrue(self.jobs()[0]['source_verification']['uncertain'])
  self.check([self.a]);self.assertFalse(self.jobs()[0]['source_verification']['uncertain'])
 def test_old_snapshot_absence_cannot_close_newer_job(self):
  self.check([self.a]);self.check([self.a,self.b]);r=self.check([self.a])
  self.assertEqual(r['closed'],0);self.assertEqual(len(self.jobs()),2);self.assertTrue(all(j['active'] for j in self.jobs()))
 def test_explicit_original_page_evidence_closes_only_reviewed_job(self):
  self.check([self.a,self.b]);self.check([]);a=next(j for j in self.jobs() if j['requisition']=='A-1')
  args=dict(id=a['id'],token=a['source_verification']['close_token'],reviewed=True,evidence_url=a['url'],reason='Synthetic original page explicitly says closed')
  with self.assertRaises(ValueError):self.s.confirm_job_closed({**args,'reviewed':False})
  with self.assertRaises(ValueError):self.s.confirm_job_closed({**args,'evidence_url':'https://other.invalid/'})
  self.s.confirm_job_closed(args);jobs=self.jobs();self.assertFalse(next(j for j in jobs if j['id']==a['id'])['active']);self.assertTrue(next(j for j in jobs if j['id']!=a['id'])['active'])
  self.assertEqual(self.check([self.a,self.b])['reopened'],1)
  with self.s.connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM settings WHERE key LIKE 'source_evidence:%'").fetchone()[0],1)
 def test_stale_confirmation_rejected_after_new_attempt(self):
  self.check([self.a]);self.check([]);a=self.jobs()[0];token=a['source_verification']['close_token']
  with patch('discovery.fetch_jobs',side_effect=TimeoutError('offline')):self.s.check_sources(self.src['id'])
  self.assertFalse(self.jobs()[0]['source_verification']['close_token'])
  with self.assertRaisesRegex(ValueError,'过期'):self.s.confirm_job_closed(dict(id=a['id'],token=token,reviewed=True,evidence_url=a['url'],reason='closed'))
 def test_late_request_cannot_overwrite_newer_snapshot(self):
  self.check([self.a]);entered=threading.Event();release=threading.Event();results=[]
  def fetch(_):
   if threading.current_thread().name=='old-snapshot':entered.set();release.wait(4);return []
   return [self.a,self.b]
  with patch('discovery.fetch_jobs',side_effect=fetch):
   worker=threading.Thread(name='old-snapshot',target=lambda:results.extend(self.s.check_sources(self.src['id'])));worker.start();self.assertTrue(entered.wait(3))
   self.s.check_sources(self.src['id']);release.set();worker.join(4);self.assertFalse(worker.is_alive())
  self.assertIn('较旧请求',results[0]['error']);self.assertTrue(all(j['active'] for j in self.jobs()));self.assertTrue(all(not j['source_verification']['uncertain'] for j in self.jobs()))
 def test_aged_record_is_unverified_without_changing_status(self):
  self.check([self.a])
  with self.s.connect(True) as db:
   row=db.execute('SELECT value FROM settings WHERE key=?',('source_review:'+str(self.src['id']),)).fetchone();info=json.loads(row[0]);info['seen_at'][self.a['source_id']]='2020-01-01T00:00:00+00:00';db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(info),'source_review:'+str(self.src['id'])))
  self.assertTrue(self.jobs()[0]['active']);self.assertTrue(self.jobs()[0]['source_verification']['uncertain'])
