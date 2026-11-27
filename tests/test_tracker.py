from email.message import EmailMessage
import unittest

from tracker import parse_notice, parse_eml, parse_eml_notice, match_application, apply_notice


PREFIX = 'Company: Example Labs\nRole: Software Intern\nJob ID: JR-123456\n'


class NoticeTests(unittest.TestCase):
    def parse(self, body, received='2026-11-18T14:08:29+08:00'):
        return parse_notice(PREFIX + body, received, 'https://example.com/recruitment/123456')

    def test_interview_original_stale_after_new_confirmation(self):
        old = self.parse('Interview invitation\nDate/Time: 24 Nov 2026 3:00am (GMT+08:00)', '2026-11-17T14:00:00+08:00')
        new = self.parse('Interview was rescheduled.\nDate/Time: 23 Nov 2026 2:00pm-3:00pm (GMT+08:00) Beijing')
        self.assertEqual(new['requisition'], 'JR-123456')
        self.assertEqual(new['interview_at'], '2026-11-23T14:00+08:00')
        self.assertEqual(old['interview_at'], '2026-11-24T03:00+08:00')
        record = apply_notice(new, apply_notice(old, None))
        self.assertEqual(record['interview_at'], new['interview_at'])
        self.assertEqual(record['last_notice_at'], '2026-11-18T14:08:29+08:00')
        stale = apply_notice(old, record)
        self.assertEqual(stale['interview_at'], new['interview_at'])
        self.assertFalse(stale['update_applied'])
        self.assertFalse(apply_notice(new, record)['update_applied'])

    def test_chinese_reschedule_and_ignore_quoted_history(self):
        notice = parse_notice('公司：甲公司\n岗位：开发实习生\n面试改期：原定2026年11月22日14:30，改到2026年11月23日下午2点30分 香港时间\n'
                              '-----Original Message-----\nInterview invitation\nDate/Time: 2026-11-24 03:00\n')
        self.assertEqual(notice['status'], 'interview')
        self.assertEqual(notice['interview_at'], '2026-11-23T14:30+08:00')

    def test_range_is_not_timezone_offset_and_iso_utc_is(self):
        self.assertEqual(self.parse('Interview invitation\nDate/Time: 2026-11-23 14:00-15:00')['interview_at'], '2026-11-23T14:00+08:00')
        event = self.parse('Interview invitation\nDate/Time: 2026-11-23T06:00:00Z')
        self.assertEqual(event['interview_at'], '2026-11-23T14:00+08:00')
        self.assertEqual(event['date_precision']['interview_at'], 'exact')
        self.assertEqual(self.parse('Interview invitation\nDate/Time: 2026-11-23T14:00-05:00')['interview_at'], '2026-11-24T03:00+08:00')

    def test_distinguishes_interview_and_reply_due_date(self):
        notice = self.parse('Interview is scheduled for 23 Nov 2026 14:00 HKT. Please reply by 21 Nov 2026 17:00 HKT.')
        self.assertEqual(notice['interview_at'], '2026-11-23T14:00+08:00')
        self.assertEqual(notice['interview_reply_by'], '2026-11-21T17:00+08:00')
        self.assertFalse(notice['deadline'])

    def test_only_explicit_reply_deadlines_belong_to_an_interview(self):
        notice = self.parse('面试通知：请于 2026-11-29 15:00 香港时间参加面试，请于 2026-11-28 前回复是否出席。')
        self.assertEqual((notice['interview_at'],notice['interview_reply_by']),('2026-11-29T15:00+08:00','2026-11-28'))
        for extra in ('Application deadline: 2026-11-25.', 'Deadline: 2026-11-25.', 'We will respond by 2026-11-25.'):
            notice = self.parse('Interview invitation. Date/Time: 2026-11-29. '+extra)
            self.assertEqual(notice['interview_at'],'2026-11-29')
            self.assertFalse(notice['interview_reply_by'])
        reminder=self.parse('请于 2026-11-28 前确认是否参加面试。')
        self.assertEqual((reminder['status'],reminder['interview_reply_by']),('interview','2026-11-28'))
        combined=self.parse('Interview invitation. Application deadline: 2026-11-25. Please reply by 2026-11-28. Date/Time: 2026-11-29.')
        self.assertEqual((combined['deadline'],combined['interview_reply_by'],combined['interview_at']),('2026-11-25','2026-11-28','2026-11-29'))

    def test_relative_extension_overrides_original_deadline(self):
        old = self.parse('Online assessment deadline 2026-11-19 09:00 HKT', '2026-11-16T12:00:00+08:00')
        new = self.parse('Online assessment: you have not completed the assessment. Please complete within another 48 hours.')
        self.assertEqual(new['deadline'], '2026-11-20T14:08+08:00')
        self.assertEqual(new['date_precision']['deadline'], 'estimated')
        self.assertEqual(new['status'], 'assessment')
        self.assertEqual(apply_notice(new, apply_notice(old, None))['deadline'], new['deadline'])

    def test_conditional_warning_is_not_rejection_and_calendar_due_is_estimated(self):
        n = self.parse('Online assessment: Please complete within five calendar days. If you do not, your application will be withdrawn.')
        self.assertEqual(n['status'], 'assessment')
        self.assertEqual(n['deadline'], '2026-11-23')
        self.assertEqual(n['date_precision']['deadline'], 'estimated')
        self.assertEqual(self.parse('We regret to inform you that your application was unsuccessful.')['status'], 'closed')

    def test_relative_date_without_anchor_and_business_days(self):
        rm = self.parse('Complete the online assessment within 48 hOurS.', None)
        self.assertFalse(rm['deadline'])
        self.assertIn('相对期限需要已核实的通知时间', rm['notes'])
        self.assertFalse(self.parse('Online assessment due within 5 business days.')['deadline'])

    def test_ambiguous_dates_not_auto_selected(self):
        due = self.parse('Online assessment. Deadline: 2026-11-20 12:00 HKT or 2026-11-22 12:00 HKT.')
        self.assertFalse(due['deadline'])
        self.assertIn('多个', due['notes'])

    def test_completed_assessment_not_in_today_queue_and_does_not_downgrade_interview(self):
        assessment = self.parse('Online assessment deadline 2026-11-19 09:00 HKT')
        completed = self.parse('Your online assessment has been successfully completed.', '2026-11-19T02:00:00Z')
        revised = apply_notice(completed, apply_notice(assessment, None))
        self.assertTrue(completed['completion'])
        self.assertEqual(revised['status'], 'waiting')
        self.assertFalse(revised['deadline'])
        scheduled = self.parse('Interview invitation\nDate/Time: 23 Nov 2026 2:00pm HKT')
        self.assertFalse(apply_notice(completed, apply_notice(scheduled, None))['update_applied'])

    def test_interview_cancelled_not_rejected(self):
        scheduled = self.parse('Interview invitation\nDate/Time: 23 Nov 2026 2:00pm HKT')
        cancelled = self.parse('Your interview has been cancelled.', '2026-11-19T03:00:00Z')
        revised = apply_notice(cancelled, apply_notice(scheduled, None))
        self.assertEqual(revised['status'], 'interview')
        self.assertEqual(revised['interview_at'], '')


class MatchTests(unittest.TestCase):
    def test_exact_id_company_and_distinct_roles(self):
        entries = [
            {'id': 1, 'company': 'Example', 'title': 'Intern', 'requisition': 'JR-0001'},
            {'id': 2, 'company': 'Example', 'title': 'Intern', 'requisition': 'JR-0002'},
            {'id': 3, 'company': 'Different', 'title': 'Intern', 'requisition': 'JR-0003'},
        ]
        self.assertEqual(match_application({'company': ' ＥＸＡＭＰＬＥ ', 'requisition': 'jr-0002'}, entries)['match_id'], 2)
        self.assertIsNone(match_application({'company': 'Example', 'requisition': 'JR_0002'}, entries)['match_id'])
        self.assertTrue(match_application({'company': 'Example', 'title': 'Intern'}, entries)['ambiguous'])
        self.assertIsNone(match_application({'company': 'Example', 'title': 'Intern', 'requisition': 'JR-0003'}, entries)['match_id'])
        self.assertIsNone(match_application({'requisition': 'JR-0003'}, entries)['match_id'])

    def test_exact_unique_title_can_backfill_missing_job_id(self):
        entries = [{'id': 1, 'company': 'Sample', 'title': 'Software Intern', 'requisition': ''}]
        n = {'company': 'Sample', 'requisition': '981', 'title': 'Software Intern', 'status': 'interview'}
        self.assertEqual(match_application(n, entries)['match_id'], 1)
        self.assertEqual(apply_notice(n, entries[0])['requisition'], '981')


class EmlTests(unittest.TestCase):
    def test_interview_subject_and_body_reply_deadline(self):
        msg = EmailMessage()
        msg['Subject'] = 'Interview invitation'
        msg.set_content(PREFIX + 'Please reply by 2026-11-28.')
        notice = parse_eml_notice(parse_eml(msg.as_bytes()))
        self.assertEqual(notice['interview_reply_by'], '2026-11-28')
        self.assertFalse(notice['deadline'])
        self.assertFalse(notice['interview_at'])

    def test_html_mail_stripped_and_sender_date_converted(self):
        eml = EmailMessage()
        eml['Subject'] = 'Interview confirmation'
        eml['From'] = 'Recruitment <recruiter@example.test>'
        eml['Date'] = 'Wed, 18 Nov 2026 14:08:29 +0000'
        eml.set_content('<div>Company: Example Labs</div><div>Role: Software Intern</div>'
                        '<p>Date/Time: 23 Nov 2026 2:00pm (GMT+08:00)</p><script>unsafe</script>', subtype='html')
        decoded = parse_eml(eml.as_bytes())
        self.assertEqual(decoded['received_at'], '2026-11-18T22:08:29+08:00')
        self.assertNotIn('unsafe', decoded['text'])
        notice = parse_notice(decoded['text'], decoded['received_at'])
        self.assertEqual(notice['company'], 'Example Labs')
        self.assertEqual(notice['interview_at'], '2026-11-23T14:00+08:00')

    def test_non_email_rejected(self):
        with self.assertRaises(ValueError):
            parse_eml(b'Not a mail message.')


if __name__ == '__main__':
    unittest.main()
