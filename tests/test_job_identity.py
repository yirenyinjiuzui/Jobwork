from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from workbench import Store
from discovery import fetch_jobs
from tracker import parse_notice

class IdentityTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.s=Store(Path(self.temp.name)/'test.sqlite3')
  self.base=dict(company='Fictional Identity Lab',title='Data Intern',location='Hong Kong',url='https://example.invalid/jobs/A',requisition='R-1',description='Analyze synthetic A data')
 def test_manual_cross_board_reused_id_separate_and_tracking_duplicate(self):
  a=self.s.save_job(self.base);b=self.s.save_job({**self.base,'url':'https://another.invalid/jobs/A','description':'Build synthetic B tools'})
  self.assertNotEqual(a['id'],b['id']);again=self.s.save_job({**self.base,'url':self.base['url']+'?utm_source=test#top','description':'Updated A'})
  self.assertEqual(a['id'],again['id']);self.assertEqual(len(self.s.state()['jobs']),2)
  self.assertTrue(all(j['identity_review'] for j in self.s.state()['jobs']))
  self.assertEqual(next(j for j in self.s.state()['jobs'] if j['id']==b['id'])['description'],'Build synthetic B tools')
 def test_distinct_ids_and_no_id_similar_pages_keep_independent_applications(self):
  for req in ('R-1',''):
   a=self.s.save_job({**self.base,'requisition':req,'url':'https://example.invalid/a'+req})
   b=self.s.save_job({**self.base,'requisition':'R-2' if req else '', 'url':'https://example.invalid/b'+req})
   aa=self.s.save_job_as_application(a['id']);bb=self.s.save_job_as_application(b['id']);self.assertNotEqual(aa['id'],bb['id'])
   self.s.save_application({**aa,'status':'interview','title':'Edited title'})
   self.s.save_application({**bb,'status':'closed'})
   self.assertEqual(self.s.save_job_as_application(a['id'])['status'],'interview');self.assertEqual(self.s.save_job_as_application(b['id'])['status'],'closed')
 def test_no_id_page_tracking_duplicate_and_functional_query_separate(self):
  d={**self.base,'requisition':'','url':'https://example.invalid/jobs?job=1&utm_source=x'}
  a=self.s.save_job(d);b=self.s.save_job({**d,'url':'https://example.invalid/jobs?job=1&utm_source=y'})
  c=self.s.save_job({**d,'url':'https://example.invalid/jobs?job=2'})
  self.assertEqual(a['id'],b['id']);self.assertNotEqual(a['id'],c['id'])
 def test_public_normalize_monitor_update_reopen_and_cross_board(self):
  source=self.s.save_source(dict(provider='greenhouse',board='fictionalidentity',company=self.base['company']))
  other=self.s.save_source(dict(provider='greenhouse',board='fictionalother',company=self.base['company']))
  rows=[dict(id=n,title='Data Intern',location={'name':'Hong Kong'},requisition_id='R-'+str(n),absolute_url='https://example.invalid/jobs/'+str(n),content='Responsibilities '+str(n)) for n in (1,2)]
  def check(src,rs):
   with patch('discovery.fetch_jobs',side_effect=lambda s:fetch_jobs(s,transport=lambda *_:{'jobs':rs})):
    return self.s.check_sources(src['id'])[0]
  check(source,[]);r=check(source,rows);self.assertTrue(r['baseline']);self.assertEqual(r['new'],0)
  original={j['source_id']:j['id'] for j in self.s.state()['jobs']};apps=[self.s.save_job_as_application(i) for i in original.values()]
  self.s.save_application({**apps[0],'status':'interview'})
  rows[0]['content']='Updated responsibilities';self.assertEqual(check(source,rows)['new'],0)
  check(source,rows[1:]);missing=next(j for j in self.s.state()['jobs'] if j['source_id'].endswith(':1'))
  self.s.confirm_job_closed(dict(id=missing['id'],token=missing['source_verification']['close_token'],reviewed=True,evidence_url=missing['url'],reason='Fictional original page says closed'))
  r=check(source,rows);self.assertEqual(r['reopened'],1);self.assertEqual(r['new'],0)
  self.assertEqual(check(source,rows)['reopened'],0);self.assertEqual(original,{j['source_id']:j['id'] for j in self.s.state()['jobs']})
  self.assertEqual(len(self.s.state()['notifications']),1)
  check(other,rows[:1]);new=next(j for j in self.s.state()['jobs'] if j['board_id']==other['id']);app=self.s.save_job_as_application(new['id'])
  self.assertNotIn(app['id'],[a['id'] for a in apps]);self.assertEqual(self.s.save_job_as_application(list(original.values())[0])['status'],'interview')
 def test_legacy_schema_rows_and_exact_page_application_reuse(self):
  old=self.s.save_application(dict(company=self.base['company'],title=self.base['title'],requisition='R-1',source_url=self.base['url']+'?utm_source=old',status='interview'))
  with self.s.connect() as db:before=db.execute('SELECT * FROM applications').fetchall();schema=db.execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall()
  a=self.s.save_job(self.base);self.assertEqual(self.s.save_job_as_application(a['id'])['id'],old['id'])
  b=self.s.save_job({**self.base,'url':'https://another.invalid/B'});self.assertNotEqual(self.s.save_job_as_application(b['id'])['id'],old['id'])
  with self.s.connect() as db:
   self.assertEqual(tuple(before[0]),tuple(db.execute('SELECT * FROM applications WHERE id=?',(old['id'],)).fetchone()))
   self.assertEqual([tuple(r) for r in schema],[tuple(r) for r in db.execute('SELECT name,sql FROM sqlite_master ORDER BY name')])

 def add_board_job(self,board):
  source=self.s.save_source(dict(provider='greenhouse',board=board,company=self.base['company']))
  row=dict(id=77,title='Data Intern',requisition_id='R-1',location={'name':'Hong Kong'})
  with patch('discovery._read_json',return_value={'jobs':[row]}):
   self.s.check_sources(source['id'])
  return next(job for job in self.s.state()['jobs'] if job['board_id']==source['id'])

 def test_removed_source_row_reuse_preserves_both_applications(self):
  a=self.add_board_job('fixture-a')
  saved=self.s.save_job_as_application(a['id'])
  notice=parse_notice('Thank you for applying.',company=a['company'],title=a['title'],requisition=a['requisition'])
  self.s.import_notice(notice,id=saved['id'],overrides={'review_confirmed':True})
  submitted=self.s.save_application({'id':saved['id'],'status':'submitted','resume_label':'A version'})
  history=self.s.history(saved['id'])
  self.assertEqual(len(history),1)
  self.s.delete_source(a['board_id'])
  b=self.add_board_job('fixture-b')
  self.assertEqual(b['id'],a['id'])
  new=self.s.save_job_as_application(b['id'])
  self.assertNotEqual(new['id'],saved['id'])
  self.assertEqual((new['source_url'],new['status']),(b['url'],'saved'))
  self.assertEqual(self.s.save_job_as_application(b['id']),new)
  # Re-adding the same board gives A a different row number.
  again=self.add_board_job('fixture-a')
  self.assertNotEqual(again['id'],a['id'])
  self.assertEqual(self.s.save_job_as_application(again['id']),submitted)
  self.assertCountEqual(self.s.applications(),[submitted,new])
  self.assertEqual(self.s.history(saved['id']),history)
  self.assertEqual(self.s.history(new['id']),[])

 def old_numeric_link(self):
  a=self.add_board_job('legacy-a')
  old=self.s.save_application(dict(company=a['company'],title='Edited title',requisition=a['requisition'],
                                   source_url=a['url']+'?utm_source=old',status='interview'))
  with self.s.connect(True) as db:
   db.execute('UPDATE applications SET identity=? WHERE id=?',('job:'+str(a['id']),old['id']))
   db.execute('INSERT INTO settings VALUES (?,?)',('job_application:'+str(a['id']),str(old['id'])))
  return a,self.s.applications()[0]

 def test_upgrade_keeps_valid_numeric_link(self):
  a,old=self.old_numeric_link()
  self.s=Store(self.s.file)
  self.assertEqual(self.s.save_job_as_application(a['id']),old)
  self.assertEqual(self.s.applications(),[old])

 def test_upgrade_skips_numeric_link_already_reused_by_another_board(self):
  a,old=self.old_numeric_link()
  self.s.delete_source(a['board_id'])
  b=self.add_board_job('legacy-b')
  self.assertEqual(b['id'],a['id'])
  self.s=Store(self.s.file)
  new=self.s.save_job_as_application(b['id'])
  self.assertEqual(new['source_url'],b['url'])
  self.assertEqual(self.s.save_job_as_application(b['id']),new)
  self.assertCountEqual(self.s.applications(),[old,new])

 def test_normalizing_an_old_manual_job_keeps_its_application(self):
  a=self.s.save_job(self.base)
  with self.s.connect(True) as db:
   db.execute('UPDATE jobs SET source_id=? WHERE id=?',('manual:old-tracking-hash',a['id']))
  saved=self.s.save_job_as_application(a['id'])
  submitted=self.s.save_application({'id':saved['id'],'status':'submitted'})
  again=self.s.save_job({**self.base,'url':self.base['url']+'?utm_source=new'})
  self.assertEqual(again['source_id'],a['source_id'])
  self.assertEqual(self.s.save_job_as_application(again['id']),submitted)
  self.assertEqual(self.s.applications(),[submitted])

if __name__=='__main__':unittest.main()
