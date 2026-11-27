"""All identities and notices below are fictional; no network or inbox access."""
from email.message import EmailMessage
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from tracker import parse_eml, parse_eml_notice, match_application
from workbench import Store

COMPANY = 'Fictional Harbor Labs'
A = {'submitted_at':'2026-11-01T10:00+08:00', 'id': 1, 'company': COMPANY, 'title': 'Data Intern', 'requisition': 'FA-1001'}
B = {'submitted_at':'2026-11-01T10:00+08:00', 'id': 2, 'company': COMPANY, 'title': 'Systems Graduate', 'requisition': 'FB-2002'}
IDENTITY = 'Company: Fictional Harbor Labs\nRole: Data Intern\nJob ID: FA-1001\n'
CLOSED = IDENTITY + 'Your application was unsuccessful.'
INTERVIEW = IDENTITY + 'Interview is confirmed.\nDate/Time: 2026-12-01 14:00 HKT'

def mail(plain=None, html=None, subject='Application update'):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = 'Fictional Recruitment <no-reply@example.invalid>'
    msg['Date'] = 'Thu, 19 Nov 2026 06:00:00 +0000'
    if plain is not None:
        msg.set_content(plain)
        if html is not None: msg.add_alternative(html, subtype='html')
    else:
        msg.set_content(html or '', subtype='html')
    return msg

def html(text):
    return ''.join('<p>' + line + '</p>' for line in text.splitlines())

def parse(plain=None, rich=None, subject='Application update', **kwargs):
    return parse_eml_notice(parse_eml(mail(plain, rich, subject).as_bytes()), **kwargs)

class MailEvidenceTests(unittest.TestCase):
    def test_footer_plain_does_not_hide_html_decision(self):
        n = parse('Please do not reply to this automated message.', html(CLOSED))
        self.assertFalse(n['requires_review'], n['warnings'])
        self.assertEqual(n['status'], 'closed')
        self.assertEqual(match_application(n, [A,B])['match_id'], 1)
        self.assertTrue(any(e['source']=='HTML 正文' and e['value']=='closed' for e in n['evidence']))

    def test_two_alternatives_conflict_in_either_order(self):
        for first, second in [(CLOSED, INTERVIEW), (INTERVIEW, CLOSED)]:
            with self.subTest(first=first):
                n = parse(first, html(second))
                self.assertTrue(n['requires_review'])
                self.assertFalse(n['has_explicit_status'])
                self.assertFalse(n['interview_at'])
                self.assertFalse(n['next_action'])
                self.assertIsNone(match_application(n,[A,B])['match_id'])
                self.assertEqual({e['value'] for e in n['evidence'] if e['field']=='status'}, {'closed','interview'})

    def test_subject_body_conflict_and_conflicting_titles(self):
        n = parse(None, html(CLOSED), subject='Interview confirmation')
        self.assertTrue(n['requires_review'])
        n = parse(CLOSED, html(CLOSED.replace('Data Intern','Systems Graduate')))
        self.assertTrue(n['requires_review'])
        self.assertFalse(n['title'])

    def test_employer_only_generic_review_never_selects_a_role(self):
        n = parse('Company: '+COMPANY+'\nYour application is under review.')
        self.assertTrue(n['requires_review'])
        self.assertIsNone(match_application(n, [A,B])['match_id'])
        self.assertFalse(n['has_explicit_status'])

    def test_only_unique_exact_company_title_without_id_can_match(self):
        n = parse(CLOSED.replace('Job ID: FA-1001\n',''))
        self.assertFalse(n['requires_review'])
        self.assertEqual(match_application(n,[A,B])['match_id'],1)
        self.assertTrue(match_application(n,[A,{**A,'id':3}])['ambiguous'])

    def test_acronyms_and_alternatives_are_not_expanded_or_preselected(self):
        for title in ['SWE','SWE Intern','Data Intern / Systems Graduate','Intern']:
            with self.subTest(title=title):
                n = parse('Company: '+COMPANY+'\nRole: '+title+'\nYour application was unsuccessful.')
                self.assertTrue(n['requires_review'])
                self.assertIsNone(match_application(n,[{**A,'title':title},B])['match_id'])

    def test_recommendations_and_links_never_supply_job_id(self):
        n = parse('Company: '+COMPANY+'\nYour application is under review.\n'
                  'https://example.invalid/jobs/JR-9999?utm_source=secret\n'
                  'Recommended jobs\nRole: Data Intern\nJob ID: FA-1001')
        self.assertFalse(n['title']);self.assertFalse(n['requisition'])
        self.assertTrue(n['requires_review'])
        n = parse(None, html('Company: '+COMPANY+'\nYour application is under review.')+
                  '<a href="https://example.invalid/jobs/FA-1001?token=secret">Job ID: FA-1001</a>')
        self.assertFalse(n['requisition'])
        self.assertNotIn('secret',json.dumps(n))

    def test_bare_id_and_attachments_are_not_identity_evidence(self):
        msg = mail('Company: '+COMPANY+'\nYour application is under review.\nJR-9999')
        msg.add_attachment(html(CLOSED).encode(),maintype='text',subtype='html',filename='other.html')
        n = parse_eml_notice(parse_eml(msg.as_bytes()))
        self.assertFalse(n['requisition']);self.assertFalse(n['title'])
        self.assertTrue(n['requires_review'])

    def test_current_decision_wins_over_quoted_history_and_recommendations(self):
        n = parse(None, html(CLOSED)+'<blockquote>'+html(INTERVIEW)+'</blockquote>'+
                  '<h2>Recommended jobs</h2><p>Job ID: FB-2002</p><p>Interview invitation</p>')
        self.assertFalse(n['requires_review'], n['warnings'])
        self.assertEqual(n['requisition'],'FA-1001');self.assertEqual(n['status'],'closed')

    def test_html_inert_hidden_attributes_urls_tracking_excluded(self):
        malicious = ('<head><style>secret CSS</style></head><script>fetch("https://example.invalid/secret")</script>'
                     '<img src="https://example.invalid/pixel?token=secret">'
                     '<div hidden>Job ID: FB-2002</div><div style="display:none">Interview invitation</div>'
                     '<a href="https://example.invalid/?utm_source=secret">Job ID: FB-2002</a>'
                     '<iframe src="https://example.invalid/secret"></iframe>')
        with patch('socket.socket',side_effect=AssertionError('No network allowed')):
            n = parse(None, malicious+html(CLOSED+'\nutm_source=secret'))
        self.assertFalse(n['requires_review'],n['warnings'])
        self.assertNotIn('secret',json.dumps(n))
        self.assertNotIn('<script',json.dumps(n))
        self.assertEqual(n['requisition'],'FA-1001')

    def test_table_identity_and_multilingual_notice(self):
        rich = '<table><tr><td>公司：</td><td>虚构港湾公司</td></tr><tr><td>岗位：</td><td>数据实习生</td></tr><tr><td>岗位编号：</td><td>FA-1001</td></tr></table><p>该申请流程终止。</p>'
        n = parse('请勿回复自动通知。',rich)
        self.assertEqual(n['company'],'虚构港湾公司')
        self.assertEqual(n['title'],'数据实习生')
        self.assertEqual(n['status'],'closed')
        self.assertFalse(n['requires_review'],n['warnings'])

    def test_conflicting_id_and_title_cannot_recommend_match(self):
        n = parse(CLOSED.replace('Job ID: FA-1001','Job ID: FB-2002'))
        result = match_application(n,[A,B])
        self.assertIsNone(result['match_id']);self.assertTrue(result['ambiguous'])

    def test_multiple_ids_do_not_pick_the_first(self):
        n = parse(CLOSED+'\nJob ID: FB-2002')
        self.assertTrue(n['requires_review']);self.assertFalse(n['requisition'])

    def test_a_changes_only_after_confirmation_and_b_interview_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'isolated.sqlite3')
            a=store.save_application({**A,'id':None,'status':'submitted'})
            b=store.save_application({**B,'id':None,'status':'interview','interview_at':'2026-12-02T14:00+08:00','next_action':'Prepare fictional interview'})
            before=store.applications()
            n=parse('Please do not reply.',html(CLOSED))
            self.assertEqual(store.applications(),before)
            match=match_application(n,store.applications())
            self.assertEqual(match['match_id'],a['id'])
            result=store.import_notice(n,id=match['match_id'])
            self.assertTrue(result['applied']);self.assertEqual(result['application']['status'],'closed')
            self.assertEqual(next(x for x in store.applications() if x['id']==b['id']),b)
            with store.connect() as db:
                history=store.rows(db,'SELECT * FROM history')
            self.assertEqual(len(history),1);self.assertIn('HTML 正文',history[0]['notes'])

    def test_conflict_requires_review_and_no_status_choice_keeps_every_field(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'isolated.sqlite3')
            a=store.save_application({**A,'id':None,'status':'interview','interview_at':'2026-12-02T14:00+08:00'})
            n=parse(CLOSED,html(INTERVIEW))
            with self.assertRaisesRegex(ValueError,'复核'):
                store.import_notice(n,id=a['id'])
            self.assertEqual(store.applications(),[a])
            result=store.import_notice(n,id=a['id'],overrides={'review_confirmed':True})
            self.assertFalse(result['applied']);self.assertEqual(result['application'],a)

    def test_reviewed_explicit_status_can_be_applied_and_identity_context_conflicts_are_visible(self):
        n=parse(CLOSED,html(INTERVIEW),title='Systems Graduate')
        self.assertTrue(n['requires_review'])
        self.assertIn('手动提供的身份与邮件正文不一致',n['warnings'])
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'isolated.sqlite3')
            a=store.save_application({**A,'id':None,'status':'submitted'})
            result=store.import_notice(n,id=a['id'],overrides={'review_confirmed':True,'status':'closed'})
            self.assertEqual(result['application']['status'],'closed')

    def test_interview_cancellation_vs_confirmation_is_a_conflict(self):
        n=parse(INTERVIEW,html(IDENTITY+'Your interview has been cancelled.'))
        self.assertTrue(n['requires_review'])
        self.assertFalse(n['interview_at'])
        self.assertFalse(n['has_explicit_status'])

    def test_repeated_consistent_alternatives_do_not_require_review(self):
        n=parse(CLOSED,html(CLOSED))
        self.assertFalse(n['requires_review'],n['warnings'])
        self.assertEqual(n['status'],'closed')

    def test_sender_and_display_name_cannot_supply_company(self):
        message=mail('Role: Data Intern\nJob ID: FA-1001\nYour application was unsuccessful.')
        message.replace_header('From',COMPANY+' <hiring@example.invalid>')
        n=parse_eml_notice(parse_eml(message.as_bytes()))
        self.assertFalse(n['company']);self.assertTrue(n['requires_review'])
        self.assertIsNone(match_application(n,[A,B])['match_id'])

    def test_unlabelled_id_in_current_body_does_not_override_exact_role(self):
        n=parse(CLOSED.replace('Job ID: FA-1001\n','')+'\nJR-9999')
        self.assertFalse(n['requisition'])
        self.assertEqual(match_application(n,[A,B])['match_id'],1)

if __name__ == '__main__':unittest.main()
