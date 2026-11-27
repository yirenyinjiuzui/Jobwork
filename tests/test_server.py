from base64 import b64encode
from datetime import datetime, timedelta
from email.message import EmailMessage
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from unittest.mock import patch

from server import WorkbenchServer, recognize_image, InputError
from workbench import HK, Store, prioritize

class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.folder.name)/'app.sqlite3')
        cls.server = WorkbenchServer(('127.0.0.1',0),cls.store)
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.folder.cleanup()

    def get(self,path):
        with urlopen(self.url+path,timeout=4) as r:
            return json.load(r)

    def post(self,path,data,*,expect=None):
        req=Request(self.url+path,json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=4) as r:
                if expect:
                    self.fail(f'expected {expect}')
                self.assertEqual(r.status,200)
                return json.load(r)
        except HTTPError as e:
            if expect is None:
                self.fail(f'{e}: {e.read().decode()}')
            self.assertEqual(e.code,expect)
            return json.load(e)

    def test_mail_submission_chronology_and_changed_confirmation(self):
        from test_mail_chronology import BASE
        from email.message import EmailMessage
        m=EmailMessage();m['Date']='Tue, 10 Nov 2026 10:00:00 +0800'
        m.set_content('Company: Fictional Timing Lab\nRole: Test Developer\nJob ID: TIME-1\nInterview invitation\nDate/Time: 2026-12-02 14:00 HKT')
        raw={'eml_base64':b64encode(m.as_bytes()).decode()}
        a=self.post('/api/application',{**BASE,'submitted_at':'2026-11-11T10:00+08:00'})['application']
        preview=self.post('/api/notice/preview',raw)
        self.assertIsNone(preview['match']['match_id']);self.assertTrue(preview['notice']['requires_review'])
        self.assertIn('2026-12-02',preview['notice']['timing_evidence']['event_at'])
        self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id']),expect=400)
        result=self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id'],overrides={'review_confirmed':True}))
        self.assertFalse(result['applied']);self.assertEqual(result['application']['status'],'saved')
        self.post('/api/application',{**a,'submitted_at':'2026-11-01T10:00+08:00'})
        preview=self.post('/api/notice/preview',raw);self.assertEqual(preview['match']['match_id'],a['id'])
        self.post('/api/application',{**a,'submitted_at':'2026-11-12T10:00+08:00'})
        error=self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id'],overrides={'review_confirmed':True}),expect=400)
        self.assertIn('重新预览',error['error'])
        self.assertEqual(next(x for x in self.get('/api/state')['applications'] if x['id']==a['id'])['status'],'saved')
        m.set_content('Company: Fictional Unknown Timing\nRole: Test Developer\nInterview invitation')
        unknown=self.post('/api/notice/preview',{'eml_base64':b64encode(m.as_bytes()).decode()})
        self.assertTrue(unknown['notice']['requires_review']);self.assertIsNone(unknown['match']['match_id'])

    def test_public_source_absence_review_http_and_confirmed_closure(self):
        from discovery import manual_job
        src=self.post('/api/source',dict(provider='greenhouse',board='httpfictional',company='Fictional HTTP Source'))['source']
        item=manual_job(dict(company='Fictional HTTP Source',title='Data Intern',url='https://example.invalid/jobs/httpA',requisition='HTTP-A'))
        item['source_id']='greenhouse:httpfictional:A'
        with patch('discovery.fetch_jobs',return_value=[item]):self.post('/api/source/check',{'id':src['id']})
        job=next(j for j in self.get('/api/state')['jobs'] if j['board_id']==src['id'])
        app=self.post('/api/job/save',{'id':job['id']})['application']
        with patch('discovery.fetch_jobs',return_value=[]):result=self.post('/api/source/check',{'id':src['id']})
        self.assertEqual(result['results'][0]['closed'],0)
        job=next(j for j in self.get('/api/state')['jobs'] if j['id']==job['id'])
        self.assertTrue(job['active']);self.assertIn('暂不可核实',job['source_verification']['message'])
        payload=dict(id=job['id'],token=job['source_verification']['close_token'],evidence_url=job['url'],reason='Synthetic page says applications are closed')
        self.post('/api/job/confirm-closed',payload,expect=400)
        confirmed=self.post('/api/job/confirm-closed',{**payload,'reviewed':True})
        self.assertFalse(confirmed['job']['active']);self.assertEqual(confirmed['evidence']['url'],job['url'])
        self.assertEqual(next(a for a in self.get('/api/state')['applications'] if a['id']==app['id']),app)
        self.post('/api/job/confirm-closed',{**payload,'reviewed':True},expect=400)
        with patch('discovery.fetch_jobs',return_value=[item]):result=self.post('/api/source/check',{'id':src['id']})
        self.assertEqual(result['results'][0]['reopened'],1)

    def test_plain_receipt_preview_and_sequential_confirmation_preserve_tasks(self):
        a=self.post('/api/application',dict(company='Fictional HTTP Receipts',title='Test Developer',requisition='ACK-A',status='assessment',deadline='2026-12-01T10:00+08:00',next_action='Keep assessment task'))['application']
        b=self.post('/api/application',dict(company='Fictional HTTP Receipts',title='Test Developer',requisition='ACK-B',status='interview',interview_at='2026-12-02T10:00+08:00'))['application']
        previews=[]
        for stamp,extra in [('2026-11-20T10:00+08:00',''),('2026-11-02T10:00+08:00',' Reference: old receipt.')]:
            preview=self.post('/api/notice/preview',dict(company=a['company'],title=a['title'],requisition=a['requisition'],received_at=stamp,text='Your application for Test Developer was submitted. Thank you for applying.'+extra))
            self.assertFalse(preview['notice']['completion']);self.assertEqual(preview['match']['match_id'],a['id']);previews.append(preview)
        for preview in previews:
            r=self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id']))
            self.assertFalse(r['applied']);self.assertEqual(r['application'],a)
        current=self.get('/api/state')['applications'];self.assertEqual(next(x for x in current if x['id']==b['id']),b)
        history=self.get('/api/history?id='+str(a['id']))
        self.assertIn('application for Test Developer',json.dumps(history))

    def test_bilingual_interview_and_history(self):
        app=self.post('/api/application',dict(company='Sample API',title='Test Intern',requisition='API-28',status='submitted'))['application']
        job2=self.post('/api/application',dict(company='Sample API',title='Test Intern',requisition='API-29',status='submitted'))['application']
        self.assertNotEqual(app['id'],job2['id'])
        for i,received,slot in [(1,'2026-11-18T14:05:40+08:00','2026-11-23 14:00'),(2,'2026-11-18T14:05:30+08:00','2026-11-24 03:00')]:
            data=dict(company='Sample API',title='Test Intern',requisition='API-28',received_at=received,
                text=f'您的面试时间已更新：{slot}（香港时间）。')
            preview=self.post('/api/notice/preview',data)
            self.assertEqual(preview['match']['match_id'],app['id'])
            self.assertEqual(len(self.get(f'/api/history?id={app["id"]}')),i-1)
            result=self.post('/api/notice/apply',dict(token=preview['token'],application_id=app['id']))
            self.assertEqual(result['applied'],i==1)
            self.assertEqual(result['application']['interview_at'],'2026-11-23T14:00+08:00')
        third=self.post('/api/notice/preview',dict(company='Sample API',title='Test Intern',requisition='API-28',
            received_at='2026-11-18T14:05:40+08:00',text='您的面试时间已更新：2026-11-23 14:00（香港时间）。'))
        self.assertTrue(self.post('/api/notice/apply',dict(token=third['token'],application_id=app['id']))['duplicate'])
        history=self.get(f'/api/history?id={app["id"]}')
        self.assertEqual([x['applied'] for x in history],[0,1])

    def test_eml_preview_preserves_estimate(self):
        prior=self.post('/api/application',dict(company='Example Hire',title='Analyst Intern',submitted_at='2026-11-01T10:00+08:00'))['application']
        msg=EmailMessage()
        msg['Subject']='Assessment Reminder'
        msg['From']='hiring@example.com'
        msg['Date']='Wed, 18 Nov 2026 06:08:00 +0000'
        msg.set_content('Assessment ID: ESTIMATE-1\nPlease complete the online assessment within the next 48 hours.')
        preview=self.post('/api/notice/preview',dict(eml_base64=b64encode(msg.as_bytes()).decode(),company='Example Hire',title='Analyst Intern'))
        record=self.post('/api/notice/apply',dict(token=preview['token'],application_id=prior['id'],overrides={'same_assessment_confirmed':True}))['application']
        self.assertEqual(record['status'],'assessment')
        self.assertEqual(record['deadline'],'2026-11-20T14:08+08:00')
        self.assertEqual(record['date_precision']['deadline'],'estimated')

    def test_discovery_checks_notifications_and_conversion(self):
        src=self.post('/api/source',dict(company='Offline Example',provider='demo',board='api-demo'))['source']
        id=src['id']
        one=self.post('/api/source/check',{'id':id})['results'][0]
        self.assertEqual((one['baseline'],one['jobs'],one['new']),(True,2,0))
        after=self.post('/api/source/check',{'id':id})['results'][0]
        self.assertEqual((after['new'],after['closed']),(1,1))
        back=self.post('/api/source/check',{'id':id})['results'][0]
        self.assertEqual(back['reopened'],1)
        state=self.get('/api/state')
        alerts=[x for x in state['notifications'] if x['title'].endswith('Offline Example')]
        self.assertEqual(len(alerts),2)
        self.post('/api/notifications/read',{'id':alerts[0]['id']})
        self.assertEqual(next(x for x in self.get('/api/state')['notifications'] if x['id']==alerts[0]['id'])['read'],1)
        job=next(x for x in state['jobs'] if x['company']=='Offline Example' and x['location']=='Hong Kong')
        self.assertEqual(job['region'],'hong_kong')
        self.assertTrue(job['eligibility'])
        applied=self.post('/api/job/save',{'id':job['id']})['application']
        self.assertEqual((applied['status'],applied['requisition']),('saved','AGENT-03'))
        self.post('/api/source/delete',{'id':id})
        self.assertIn(applied['id'],[x['id'] for x in self.get('/api/state')['applications']])

    def test_profile_and_manual_job(self):
        self.post('/api/company',{'name':'Campus Example','career_url':'https://example.com/jobs'})
        job=self.post('/api/job',dict(company='Campus Example',title='Graduate Engineer',location='深圳',
                    url='https://example.com/jobs/77',eligibility='2027 届',start='明年夏季'))['job']
        self.assertEqual(job['career_type'],'graduate')
        self.assertEqual(job['eligibility'],'2027 届')
        profile=self.post('/api/profile',{'full_name':'示例用户','email':'sample@example.com','answers':{'Why':'Test'},'ignored_key':'hidden'})['profile']
        self.assertNotIn('ignored_key',profile)
        self.assertEqual(self.get('/api/state')['profile']['full_name'],'示例用户')
        details={'target_position':'测试开发','education':[{'school':'示例大学','end':'2027-06','unknown':'ignored'},{}]}
        saved=self.post('/api/profile',{'full_name':'示例用户','resume_details':details})['profile']['resume_details']
        self.assertEqual(saved['education'],[{'school':'示例大学','end':'2027-06'}])
        self.post('/api/profile',{'full_name':'旧页面保存'})
        self.assertEqual(self.get('/api/state')['profile']['resume_details'],saved)
        details['family_relations']=[{'name':'演示家人','relation':'演示关系'}]
        expanded=self.post('/api/profile',{'resume_fields_version':1,'resume_details':details})['profile']['resume_details']
        self.assertEqual(expanded['family_relations'],[{'name':'演示家人','relation':'演示关系'}])
        stale=self.post('/api/profile',{'resume_details':{'education':[]}},expect=400)
        self.assertIn('刷新页面',stale['error'])
        self.assertEqual(self.get('/api/state')['profile']['resume_details'],expanded)

    def test_manual_job_reuses_old_tracking_url_identity(self):
        data=dict(company='Migration Example',title='Engineer Intern',location='Hong Kong',career_type='intern',
                  url='https://example.com/jobs/88?utm_source=social&jobId=88')
        original=self.post('/api/job',data)['job']
        with self.store.connect(True) as db:
            db.execute('UPDATE jobs SET source_id=? WHERE id=?',('manual:legacy-hash',original['id']))
        again=self.post('/api/job',{**data,'url':'https://example.com/jobs/88?jobId=88'})['job']
        self.assertEqual(again['id'],original['id'])
        self.assertNotEqual(again['source_id'],'manual:legacy-hash')
        other=self.post('/api/job',{**data,'url':'https://example.com/jobs/88?jobId=99'})['job']
        self.assertNotEqual(other['id'],again['id'])

    def test_cross_origin_dns_rebinding_and_raw_posts_denied(self):
        for headers,code in [({'Host':'evil.test','Content-Type':'application/json'},403),
                              ({'Origin':'https://evil.test','Content-Type':'application/json'},403),
                              ({'Content-Type':'text/plain'},415)]:
            conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
            conn.request('POST','/api/profile','{}',headers)
            r=conn.getresponse(); r.read()
            self.assertEqual(r.status,code)
            conn.close()
        with self.assertRaises(HTTPError):
            urlopen(self.url+'/../workbench.py',timeout=3)

    def test_relative_date_uncertainty_in_today(self):
        t=datetime(2026,11,19,12,tzinfo=HK)
        rows=[dict(id=1,status='waiting'),dict(id=2,status='assessment',deadline=(t+timedelta(hours=25)).isoformat(),date_precision={'deadline':'estimated'})]
        tasks=prioritize(rows,t)
        self.assertEqual([x['id'] for x in tasks],[2])
        self.assertIn('推算',tasks[0]['reason'])

    def test_bad_file_and_ocr_failure_stay_local(self):
        self.post('/api/notice/preview',{'eml_base64':'###'},expect=400)
        self.post('/api/ocr',{'image_base64':b64encode(b'plain text').decode()},expect=400)
        with patch('server.shutil.which',return_value=None),patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(InputError,'未找到'):
                recognize_image({'image_base64':b64encode(b'\x89PNG\r\n\x1a\n').decode()})

    def test_csv_escapes_formula_like_content(self):
        self.post('/api/application',dict(company='CSV Example',title='=1+1',requisition='CSV-1'))
        with urlopen(self.url+'/api/export',timeout=3) as r:
            body=r.read().decode('utf-8-sig')
            self.assertIn("CSV Example,'=1+1,",body)

    def test_mime_html_decision_preview_confirmation_isolates_roles(self):
        from test_mail_evidence import mail, html, CLOSED, COMPANY
        a=self.post('/api/application',dict(submitted_at='2026-11-01T10:00+08:00',company=COMPANY,title='Data Intern',requisition='FA-1001',status='submitted'))['application']
        b=self.post('/api/application',dict(submitted_at='2026-11-01T10:00+08:00',company=COMPANY,title='Systems Graduate',requisition='FB-2002',status='interview',interview_at='2026-12-02T14:00+08:00'))['application']
        before=self.get('/api/state')['applications']
        message=mail('Please do not reply.',html(CLOSED))
        preview=self.post('/api/notice/preview',dict(eml_base64=b64encode(message.as_bytes()).decode()))
        self.assertEqual(preview['match']['match_id'],a['id'])
        self.assertEqual(preview['notice']['status'],'closed')
        self.assertEqual(self.get('/api/state')['applications'],before)
        self.post('/api/notice/apply',dict(token=preview['token'],application_id=b['id']),expect=400)
        self.assertEqual(self.get('/api/state')['applications'],before)
        updated=self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id']))
        self.assertEqual(updated['application']['status'],'closed')
        current=self.get('/api/state')['applications']
        self.assertEqual(next(x for x in current if x['id']==b['id']),b)
        self.assertEqual(self.get('/api/history?id='+str(b['id'])),[])
        self.assertIn('HTML 正文',self.get('/api/history?id='+str(a['id']))[0]['notes'])

    def test_mime_conflict_api_requires_review_and_keeps_no_change_default(self):
        from test_mail_evidence import mail, html, CLOSED, INTERVIEW, COMPANY
        a=self.post('/api/application',dict(company='Conflict '+COMPANY,title='Data Intern',requisition='FC-3003',status='interview',interview_at='2026-12-03T14:00+08:00'))['application']
        plain=CLOSED.replace(COMPANY,'Conflict '+COMPANY).replace('FA-1001','FC-3003')
        rich=INTERVIEW.replace(COMPANY,'Conflict '+COMPANY).replace('FA-1001','FC-3003')
        preview=self.post('/api/notice/preview',dict(eml_base64=b64encode(mail(plain,html(rich)).as_bytes()).decode()))
        self.assertTrue(preview['notice']['requires_review'])
        self.assertFalse(preview['notice']['has_explicit_status'])
        self.assertIsNone(preview['match']['match_id'])
        self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id']),expect=400)
        result=self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id'],overrides={'review_confirmed':True}))
        self.assertFalse(result['applied']);self.assertEqual(result['application'],a)
        self.assertEqual(self.get('/api/history?id='+str(a['id']))[0]['applied'],0)

    def test_mime_unknown_role_under_known_employer_cannot_default_status(self):
        from test_mail_evidence import mail
        company='Fictional Unknown Role Employer'
        a=self.post('/api/application',dict(company=company,title='Software Engineer Intern',requisition='FU-1001',status='interview'))['application']
        message=mail('Company: '+company+'\nRole: SWE intern\nYour application was unsuccessful.')
        preview=self.post('/api/notice/preview',dict(eml_base64=b64encode(message.as_bytes()).decode()))
        self.assertTrue(preview['notice']['requires_review'])
        self.assertFalse(preview['notice']['has_explicit_status'])
        self.assertIsNone(preview['match']['match_id'])
        self.post('/api/notice/apply',dict(token=preview['token'],application_id=a['id']),expect=400)

if __name__=='__main__':
    unittest.main()
