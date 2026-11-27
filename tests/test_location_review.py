from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from location_review import assess_location
from workbench import Store

def job(description='',location='Hong Kong',title='Fictional Data Intern'):
    return dict(company='Fictional Harbor',title=title,location=location,description=description,
                career_type='intern',url='https://example.invalid/jobs/A',requisition='F-1001')

class LocationTests(unittest.TestCase):
    def test_real_hong_kong_and_overseas_headquarters(self):
        for body in ['The internship is based in Hong Kong.', 'Our headquarters are in London. The internship is based in Hong Kong.', '实习地点：香港。总部位于新加坡。']:
            n=assess_location(job(body))
            self.assertTrue(n['hk_onsite'],body);self.assertFalse(n['requires_review'])

    def test_overseas_internship_and_hong_kong_conversion(self):
        for body in ['The internship is based in Singapore. After graduation the permanent role is in Hong Kong.', '实习地点：深圳，毕业后转正到香港。', 'The internship is based in Singapore and after graduation the role is in Hong Kong.']:
            n=assess_location(job(body))
            self.assertEqual(n['status'],'conflict',body);self.assertFalse(n['hk_onsite'])
            self.assertTrue(n['requires_review'])

    def test_required_rotation_distinguished_from_placement_conflict(self):
        for body in ['The internship is based in Hong Kong. Mandatory training in Singapore is required.', '实习地点：香港。必须赴深圳培训。', 'The internship is based in Hong Kong, but mandatory training in Singapore is required.']:
            n=assess_location(job(body))
            self.assertEqual(n['status'],'rotation',body);self.assertIn('必须',n['reason'])
            self.assertFalse(n['hk_onsite'])

    def test_optional_rotation_still_requires_review_without_claiming_required(self):
        n=assess_location(job('The internship is based in Hong Kong. Optional training in Singapore is available.'))
        self.assertEqual(n['status'],'rotation');self.assertIn('是否必须',n['reason'])

    def test_missing_or_future_only_or_ambiguous_is_not_hk_onsite(self):
        for body in ['', 'Our headquarters are in London.', 'After graduation interns will work in Hong Kong.', 'Hong Kong recruiting office.', 'The internship may be based in Hong Kong.', '[摘录不完整] The internship is based in Hong Kong.']:
            n=assess_location(job(body))
            self.assertTrue(n['requires_review'],body);self.assertFalse(n['hk_onsite'])
        self.assertTrue(assess_location(job('',location=''))['requires_review'])

    def test_structured_location_conflict_is_not_overwritten(self):
        data=job('The internship is based in Hong Kong.',location='Singapore')
        before=dict(data);n=assess_location(data)
        self.assertEqual(data,before);self.assertEqual(n['status'],'conflict')

    def test_evidence_bounded_source_labels_and_no_tracking(self):
        data=job('[正文:元数据] The internship is based in Singapore. [正文:可见] After graduation the permanent role is in Hong Kong. https://example.invalid/?token=secret')
        n=assess_location(data)
        self.assertEqual(n['status'],'conflict')
        self.assertIn('JobPosting.description',{e['source'] for e in n['evidence']})
        self.assertIn('可见岗位正文',{e['source'] for e in n['evidence']})
        self.assertNotIn('secret',str(n));self.assertTrue(all(len(e['quote'])<=180 for e in n['evidence']))

    def test_existing_database_read_without_migration_or_raw_data_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'existing.sqlite3';store=Store(file)
            saved=store.save_job(job('The internship is based in Singapore. After graduation the role is in Hong Kong.'))
            with closing(sqlite3.connect(file)) as db, db:
                before=db.execute('SELECT * FROM jobs').fetchall();schema=db.execute('PRAGMA table_info(jobs)').fetchall()
            again=Store(file);rows=again.state()['jobs']
            self.assertEqual(rows[0]['location'],'Hong Kong');self.assertEqual(rows[0]['location_review']['status'],'conflict')
            with closing(sqlite3.connect(file)) as db, db:
                self.assertEqual(before,db.execute('SELECT * FROM jobs').fetchall())
                self.assertEqual(schema,db.execute('PRAGMA table_info(jobs)').fetchall())
            self.assertEqual(saved['id'],rows[0]['id'])

    def test_legacy_no_description_remains_readable_and_reviewable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'legacy.sqlite3');saved=store.save_job(job())
            self.assertEqual(saved['location_review']['status'],'missing')
            self.assertEqual(store.state()['jobs'][0]['location'],'Hong Kong')
            app=store.save_job_as_application(saved['id'])
            self.assertEqual(app['location'],'Hong Kong')

    def test_non_intern_not_reclassified_and_clear_other_city_not_in_hk_review(self):
        self.assertEqual(assess_location({**job(),'career_type':'graduate'})['status'],'not_intern')
        self.assertEqual(assess_location(job('The internship is based in Singapore.',location='Singapore'))['status'],'other')

    def test_unknown_second_placement_negation_and_unspecified_training_are_reviewed(self):
        for body in ['The internship is based in Hong Kong. The internship is based in Paris.', 'The internship is based in Hong Kong. The internship is not based in Hong Kong.', 'The internship is based in Hong Kong. Mandatory training is required.']:
            n=assess_location(job(body));self.assertFalse(n['hk_onsite'],body);self.assertTrue(n['requires_review'])

    def test_optional_training_does_not_claim_mandatory(self):
        n=assess_location(job('The internship is based in Hong Kong. Training in Singapore is not mandatory.'))
        self.assertIn('是否必须',n['reason'])

    def test_legacy_summary_near_truncation_limit_is_not_sufficient_for_hk_recommendation(self):
        n=assess_location(job('The internship is based in Hong Kong. '+('More details. '*60)[:555]))
        self.assertTrue(n['requires_review']);self.assertFalse(n['hk_onsite'])

if __name__=='__main__':unittest.main()
