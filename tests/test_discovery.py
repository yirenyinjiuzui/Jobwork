import io
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import discovery as d


GH = {"provider": "greenhouse", "board": "Acme", "company": "Acme"}
LEVER = {"provider": "lever_eu", "board": "Acme", "company": "Acme"}
SMART = {"provider": "smartrecruiters", "board": "Acme", "company": "Acme"}
ASHBY = {"provider": "ashby", "board": "Acme", "company": "Acme"}
DEMO = {"provider": "demo", "board": "showcase", "company": "示例公司"}

def gh_row(job_id=101, **updates):
    return {
        "id": job_id, "title": "Data Engineering Intern", "requisition_id": "REQ-123",
        "location": {"name": "Hong Kong"},
        "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{job_id}",
        "content": "&lt;p&gt;申请截止：2026年12月2日&lt;/p&gt;&lt;p&gt;Start date: January&lt;/p&gt;",
        **updates,
    }

def lev_row(job_id, **updates):
    return {
        "id": f"uuid-{job_id}", "text": "Data Engineer", "categories": {
            "location": "Hong Kong", "allLocations": ["hong kong", "深圳"], "commitment": "Intern",
        },
        "hostedUrl": f"https://jobs.eu.lever.co/acme/uuid-{job_id}",
        "descriptionPlain": "Application deadline: 2026-12-02T20:30:00+08:00\nEligibility: Graduation in 2027",
        **updates,
    }

def ashby_row(posting_id="abcd-ef00", **updates):
    return {
        "title": "AI Engineer", "location": "Kwun Tong", "employmentType": "Intern",
        "address": {"postalAddress": {"addressCountry": "HK"}},
        "secondaryLocations": [{"location": "Shenzhen", "address": {"addressCountry": "CN"}}],
        "jobUrl": f"https://jobs.ashbyhq.com/Acme/{posting_id}?utm_source=feed",
        "applyUrl": f"https://jobs.ashbyhq.com/acme/{posting_id}/application",
        "isListed": True,
        "descriptionHtml": "<p>Application deadline: 2026-12-02</p><p>毕业时间：2027 年</p>",
        **updates,
    }

def ashby_payload(*rows):
    return {"apiVersion": "1", "jobs": list(rows)}


def smart_row(posting_id=42, **updates):
    return {
        "id": str(posting_id), "uuid": f"9a9a-posting-{posting_id}", "name": "Data Engineer",
        "refNumber": "REF-007", "company": {"identifier": "ACME", "name": "Acme Inc."},
        "location": {"city": "Kwun Tong", "country": "HK", "remote": False},
        "typeOfEmployment": {"label": "Intern"},
        "releasedDate": "2026-11-01T03:00:00Z",
        "postingUrl": f"https://jobs.smartrecruiters.com/ACME/{posting_id}-data-engineer?source=example",
        "customField": [{"fieldLabel": "Application deadline", "valueLabel": "2026-12-08"}],
        **updates,
    }

def smart_payload(*rows, total=None, offset=0, limit=100):
    return {"limit": limit, "offset": offset,
            "totalFound": len(rows) if total is None else total, "content": list(rows)}


class DiscoveryTests(unittest.TestCase):
    def test_source_tokens_and_official_urls(self):
        self.assertEqual(d.validate_source(GH), {**GH, "board": "acme"})
        self.assertEqual(d.validate_source({"company": "Acme", "board":
            "https://job-boards.eu.greenhouse.io/Acme/jobs/42?utm_source=sample"}),
            {"provider": "greenhouse_eu", "board": "acme", "company": "Acme"})
        self.assertEqual(d.validate_source({**LEVER, "board":
            "https://api.eu.lever.co/v0/postings/acme?mode=json"})["board"], "acme")
        self.assertEqual(d.validate_source({**GH, "board":
            "https://boards.greenhouse.io/embed/job_board?for=acme"})["board"], "acme")

    def test_invalid_source_urls_never_reach_transport(self):
        invalid = [
            "http://job-boards.greenhouse.io/acme", "https://job-boards.greenhouse.io.evil.example/acme",
            "https://job-boards.greenhouse.io@evil.example/acme", "https://job-boards.greenhouse.io:99/acme",
            "https://boards-api.greenhouse.io/v1/boards/%2e%2e/jobs", "https://[invalid/acme",
            "https://api.lever.co/v0/postings/acme", "https://localhost/secret", "//evil.example/test",
        ]
        for board in invalid:
            with self.subTest(board=board), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs({**GH, "board": board}, transport=lambda *_: self.fail("unexpected outbound request"))

    def test_greenhouse_normalization_and_deadline(self):
        def fetch(url, timeout):
            self.assertGreater(timeout, 0)
            self.assertEqual(url, "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true")
            return {"jobs": [gh_row()], "meta": {"total": 1}}
        job, = d.fetch_jobs(GH, transport=fetch)
        self.assertEqual(job["source_id"], "greenhouse:acme:101")
        self.assertEqual(job["career_type"], "intern")
        self.assertEqual(job["region"], "hong_kong")
        self.assertEqual(job["requisition"], "REQ-123")
        self.assertEqual(job["deadline"], "2026-12-02")
        self.assertEqual(job["start"], "January")
        self.assertNotIn("<p>", job["description"])

    def test_greenhouse_eu_uses_documented_endpoint(self):
        source = {**GH, "provider": "greenhouse_eu"}
        job, = d.fetch_jobs(source, transport=lambda url, _:
            {"jobs": [gh_row(absolute_url="javascript:alert(1)")], "meta": {"total": 1}})
        self.assertEqual(job["url"], "https://job-boards.eu.greenhouse.io/acme/jobs/101")

    def test_lever_pagination_and_eu(self):
        calls = []
        def fetch(url, _):
            parts = urlsplit(url)
            self.assertEqual(parts.netloc, "api.eu.lever.co")
            self.assertEqual(parts.path, "/v0/postings/acme")
            query = parse_qs(parts.query)
            self.assertEqual(query["mode"], ["json"])
            skip = int(query["skip"][0])
            calls.append(skip)
            return [lev_row(i) for i in range(101)][skip:skip + int(query["limit"][0])]
        jobs = d.fetch_jobs(LEVER, transport=fetch)
        self.assertEqual(calls, [0, 100, 101])
        self.assertEqual(len(jobs), 101)
        self.assertEqual(jobs[0]["location"], "Hong Kong / 深圳")
        self.assertEqual(jobs[0]["region"], "both")
        self.assertEqual(jobs[0]["career_type"], "intern")
        self.assertEqual(jobs[0]["deadline"], "2026-12-02T20:30:00+08:00")
        self.assertEqual(jobs[0]["eligibility"], "Graduation in 2027")

    def test_lever_short_page_and_country_code(self):
        calls = []
        def fetch(url, _):
            skip = int(parse_qs(urlsplit(url).query)["skip"][0])
            calls.append(skip)
            return [lev_row(skip, country="HK", categories={"location": "Kwun Tong"})] if skip < 2 else []
        jobs = d.fetch_jobs(LEVER, transport=fetch)
        self.assertEqual(calls, [0, 1, 2])
        self.assertEqual([job["region"] for job in jobs], ["hong_kong", "hong_kong"])

    def test_ashby_sources_use_fixed_host_and_normalize_case(self):
        out = d.validate_source({"company": "Acme", "board":
            "https://jobs.ashbyhq.com/Acme/ABCD-1234/application?x=y"})
        self.assertEqual(out, {**ASHBY, "board": "acme"})
        out2 = d.validate_source({**ASHBY, "board":
            "https://api.ashbyhq.com/posting-api/job-board/Acme?includeCompensation=true"})
        self.assertEqual(out, out2)
        self.assertEqual(d.board_url(out), "https://jobs.ashbyhq.com/acme")
        invalid = [
            "https://api.ashbyhq.com/company.list", "https://jobs.ashbyhq.com.evil.example/Acme",
            "https://jobs.ashbyhq.com:8181/Acme", "https://api.ashbyhq.com/posting-api/job-board/",
        ]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs({**ASHBY, "board": url}, transport=lambda *_: self.fail("unexpected network"))

    def test_ashby_normalizes_published_jobs_and_omits_unlisted(self):
        def fetch(url, _):
            self.assertEqual(url, "https://api.ashbyhq.com/posting-api/job-board/acme")
            return ashby_payload(ashby_row("AbCd-Ef00"), {"isListed": False})
        job, = d.fetch_jobs(ASHBY, transport=fetch)
        self.assertEqual(job["title"], "AI Engineer")
        self.assertEqual(job["career_type"], "intern")
        self.assertEqual(job["url"], "https://jobs.ashbyhq.com/Acme/AbCd-Ef00")
        self.assertEqual(job["source_id"], "ashby:acme:abcd-ef00")
        self.assertEqual(job["location"], "Kwun Tong / Shenzhen")
        self.assertEqual(job["region"], "both")
        self.assertEqual(job["requisition"], "")
        self.assertEqual(job["deadline"], "2026-12-02")
        self.assertEqual(job["eligibility"], "2027 年")

    def test_ashby_can_use_trusted_apply_link_without_inventing_requisition(self):
        job, = d.fetch_jobs(ASHBY, transport=lambda *_: ashby_payload(
            ashby_row(jobUrl=None, requisitionId="ASH-12", title="Graduates Program",
                      location=None, address={}, secondaryLocations=[], employmentType="FullTime")))
        self.assertEqual(job["source_id"], "ashby:acme:abcd-ef00")
        self.assertEqual(job["requisition"], "ASH-12")
        self.assertEqual(job["career_type"], "graduate")
        self.assertEqual(job["region"], "unknown")
        self.assertEqual(job["url"], "https://jobs.ashbyhq.com/acme/abcd-ef00")

    def test_ashby_empty_vs_invalid_payload_or_inconsistent_identity(self):
        self.assertEqual(d.fetch_jobs(ASHBY, transport=lambda *_: ashby_payload()), [])
        payloads = [
            {"jobs": []}, {"apiVersion": "2", "jobs": []}, {"apiVersion": "1", "jobs": None},
            ashby_payload(ashby_row(isListed=None)), ashby_payload(ashby_row(isListed="false")),
            ashby_payload(ashby_row(jobUrl=None, applyUrl=None)),
            ashby_payload(ashby_row(jobUrl="https://jobs.ashbyhq.com/other/abcd-ef00")),
            ashby_payload(ashby_row(applyUrl="https://jobs.ashbyhq.com/acme/does-not-match/apply")),
            ashby_payload(ashby_row("abcd-ef00"), ashby_row("ABCD-EF00")),
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs(ASHBY, transport=lambda *_: payload)

    def test_smartrecruiters_source_url_validation(self):
        expected = {**SMART, "board": "acme"}
        candidates = [
            "https://careers.smartrecruiters.com/ACME",
            "https://jobs.smartrecruiters.com/Acme/42-data-engineer",
            "https://api.smartrecruiters.com/v1/companies/acme/postings?destination=INTERNAL",
        ]
        for link in candidates:
            self.assertEqual(d.validate_source({"company": "Acme", "board": link}), expected)
        for invalid in (
            "https://jobs.smartrecruiters.com.bad.test/acme",
            "https://careers.smartrecruiters.com:8080/Acme",
            "https://api.smartrecruiters.com/feed/publications",
            "https://api.smartrecruiters.com/v1/companies/acme/jobs",
            "https://api.smartrecruiters.com/v1/companies/%2e%2e/postings",
        ):
            with self.subTest(link=invalid), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs({**SMART, "board": invalid}, transport=lambda *_: self.fail("unexpected network"))
        self.assertEqual(d.board_url(SMART), "https://careers.smartrecruiters.com/acme")

    def test_smartrecruiters_public_pages_and_normalization(self):
        calls = []
        def read(url, timeout):
            parts = urlsplit(url)
            self.assertEqual(parts.scheme, "https")
            self.assertEqual(parts.netloc, "api.smartrecruiters.com")
            self.assertEqual(parts.path, "/v1/companies/acme/postings")
            query = parse_qs(parts.query)
            self.assertEqual(set(query), {"destination", "limit", "offset"})
            self.assertEqual(query["destination"], ["PUBLIC"])
            self.assertEqual(query["limit"], ["100"])
            self.assertGreater(timeout, 0)
            offset = int(query["offset"][0])
            calls.append(offset)
            if offset == 0:
                return smart_payload(smart_row(), total=2, limit=1)
            return smart_payload(smart_row(19, name="2026 Graduate Software Engineer",
                            postingUrl=None, refNumber="", customField=[],
                            location={"city": "Nanning", "country": "CN"},
                            typeOfEmployment={"label": "Full-time"}), total=2, offset=1, limit=1)
        a, b = d.fetch_jobs({**SMART, "board": "https://api.smartrecruiters.com/v1/companies/Acme/postings?destination=INTERNAL"},
                            transport=read)
        self.assertEqual(calls, [0, 1])
        self.assertEqual(a["source_id"], "smartrecruiters:acme:42")
        self.assertEqual(a["location"], "Kwun Tong / HK")
        self.assertEqual(a["region"], "hong_kong")
        self.assertEqual(a["career_type"], "intern")
        self.assertEqual(a["deadline"], "2026-12-08")
        self.assertEqual(a["requisition"], "REF-007")
        self.assertEqual(a["url"], "https://jobs.smartrecruiters.com/ACME/42-data-engineer")
        self.assertEqual(b["region"], "mainland")
        self.assertEqual(b["career_type"], "graduate")
        self.assertEqual(b["url"], "https://careers.smartrecruiters.com/acme")
        self.assertEqual(b["deadline"], "")  # releasedDate is not a deadline

    def test_smartrecruiters_uuid_and_trusted_link_fallback(self):
        row = smart_row(id=None, uuid="abcd-1234", postingUrl="https://untrusted.example/acme/42",
                        applyUrl="https://www.smartrecruiters.com/acme/42-data-engineer?oga=true")
        job, = d.fetch_jobs(SMART, transport=lambda *_: smart_payload(row))
        self.assertEqual(job["source_id"], "smartrecruiters:acme:abcd-1234")
        self.assertEqual(job["url"], "https://www.smartrecruiters.com/acme/42-data-engineer")
        row["applyUrl"] = "https://jobs.smartrecruiters.com/different-board/42-data-engineer"
        job, = d.fetch_jobs(SMART, transport=lambda *_: smart_payload(row))
        self.assertEqual(job["url"], "https://careers.smartrecruiters.com/acme")

    def test_smartrecruiters_empty_is_distinct_from_incomplete_or_changed_board(self):
        self.assertEqual(d.fetch_jobs(SMART, transport=lambda *_: smart_payload()), [])
        for invalid in (
            {"content": []},
            smart_payload(total=1),
            smart_payload(smart_row(), total=0),
            smart_payload(smart_row(), offset=2),
            smart_payload(smart_row(), total=d.MAX_ROWS + 1),
            smart_payload(smart_row(company={"identifier": "other-co"})),
            smart_payload(smart_row(id="error/value")),
        ):
            with self.subTest(payload=invalid), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs(SMART, transport=lambda *_: invalid)
        for second in (
            smart_payload(smart_row(4), total=3, offset=1),
            smart_payload(smart_row(), total=2, offset=1),
            smart_payload(total=2, offset=1),
            smart_payload(smart_row(4), total=2, offset=0),
        ):
            pages = iter([smart_payload(smart_row(), total=2), second])
            with self.subTest(second=second), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs(SMART, transport=lambda *_: next(pages))

    def test_partial_snapshot_and_duplicate_pages_raise(self):
        checks = [
            (GH, {"jobs": [gh_row()], "meta": {"total": 2}}),
            (GH, {"jobs": [gh_row(), gh_row()]}),
            (GH, {"jobs": [{"title": "Unknown"}]}),
            (GH, {"error": "not found"}),
            (LEVER, [lev_row(i) for i in range(100)]),  # First page repeated
            (LEVER, {"status": "bad"}),
        ]
        for source, payload in checks:
            with self.subTest(provider=source["provider"], payload_type=type(payload).__name__), self.assertRaises(d.DiscoveryError):
                d.fetch_jobs(source, transport=lambda *_: payload)

    def test_valid_empty_and_network_error_are_distinct(self):
        self.assertEqual(d.fetch_jobs(GH, transport=lambda *_: {"jobs": [], "meta": {"total": 0}}), [])
        self.assertEqual(d.fetch_jobs(LEVER, transport=lambda *_: []), [])
        def outage(*_):
            raise URLError("not reachable")
        with self.assertRaises(d.DiscoveryError):
            d.fetch_jobs(GH, transport=outage)

    def test_http_redirect_handler_never_follows(self):
        handler = d._NoRedirect()
        with self.assertRaises(HTTPError):
            handler.redirect_request(d.Request("https://boards-api.greenhouse.io/"),
                io.BytesIO(b""), 302, "Found", {}, "https://elsewhere.example/")

    def test_read_json_rejects_unlisted_host_before_open(self):
        with patch("discovery.build_opener") as opener, self.assertRaises(d.DiscoveryError):
            d._read_json("https://example.invalid/greenhouse", 1)
        opener.assert_not_called()

    def test_initial_baseline_then_new_closed_and_reopened(self):
        baseline = d.detect_changes([], d.fetch_jobs(DEMO), initialized=False)
        self.assertTrue(baseline["baseline"])
        self.assertFalse(baseline["new"])
        second = d.detect_changes(baseline["jobs"], d.demo_jobs(DEMO, 1), initialized=True)
        self.assertEqual([x["requisition"] for x in second["new"]], ["AGENT-03"])
        self.assertEqual([x["requisition"] for x in second["closed"]], ["QA-01"])
        self.assertFalse(second["closed"][0]["active"])
        repeated = d.detect_changes(second["jobs"], d.demo_jobs(DEMO, 1), initialized=True)
        self.assertFalse(repeated["new"])
        self.assertFalse(repeated["closed"])
        self.assertEqual(len(repeated["jobs"]), 3)
        third = d.detect_changes(second["jobs"], d.demo_jobs(DEMO, 2), initialized=True)
        self.assertEqual([x["requisition"] for x in third["reopened"]], ["QA-01"])
        self.assertFalse(third["new"])
        self.assertEqual(sum(row["active"] for row in third["jobs"]), 3)

    def test_subsequent_empty_closes_old_jobs_once(self):
        first = d.detect_changes([], d.demo_jobs(DEMO), initialized=False)
        second = d.detect_changes(first["jobs"], [], initialized=True)
        self.assertEqual(len(second["closed"]), 2)
        self.assertEqual(len(second["jobs"]), 2)
        self.assertEqual(d.detect_changes(second["jobs"], [], initialized=True)["closed"], [])

    def test_manual_identity_ignores_case_and_does_not_merge_titles(self):
        data = {"company": "ACME", "title": "AI 工程师（校招）", "location": "深圳",
                "url": "https://acme.example/jobs", "deadline": "2026-12-01"}
        job = d.manual_job({**data, "requisition": "Req-1"})
        revised = d.manual_job({**data, "company": "acme", "requisition": "req-1", "title": "Edited title"})
        other = d.manual_job({**data, "requisition": "REQ-2"})
        self.assertEqual(job["source_id"], revised["source_id"])
        self.assertNotEqual(job["source_id"], other["source_id"])
        self.assertNotEqual(d.manual_job(data)["source_id"],
                            d.manual_job({**data, "title": "不同岗位"})["source_id"])
        self.assertEqual(job["career_type"], "graduate")
        self.assertEqual(job["region"], "mainland")
        self.assertEqual(job["deadline"], "2026-12-01")

    def test_manual_link_tracking_is_ignored_but_functional_values_are_not(self):
        common = {"company": "Acme", "title": "AI 实习生", "location": "香港"}
        first = "https://WWW.ZHIPIN.COM/web/geek/job?securityId=ABC%2F23&utm_source=feed&gh_src=extra#page"
        second = "https://www.zhipin.com/web/geek/job?fbclid=xyz&securityId=ABC%2F23&gclid=one"
        distinct = "https://www.zhipin.com/web/geek/job?securityId=ABC%2F24&gclid=one"
        extra_functional = "https://www.zhipin.com/web/geek/job?securityId=ABC%2F23&source=123"
        capture = lambda url: d.manual_job({**common, "url": url})
        a, b, c, e = (capture(link) for link in (first, second, distinct, extra_functional))
        self.assertEqual(a["source_id"], b["source_id"])
        self.assertNotEqual(a["source_id"], c["source_id"])
        self.assertNotEqual(a["source_id"], e["source_id"])
        self.assertEqual(a["url"], first)
        self.assertEqual(b["url"], second)

    def test_invalid_or_non_explicit_dates_not_inferred(self):
        job, = d.fetch_jobs(GH, transport=lambda *_: {"jobs": [
            gh_row(content="Training starts 2026-02-25. Apply by Friday.", deadline="2026-02-30")]})
        self.assertEqual(job["deadline"], "")
        for deadline in ("2026-02-30", "2026-02-28T09:00", "Friday"):
            with self.assertRaises(d.DiscoveryError):
                d.manual_job({"company": "A", "title": "B", "url": "https://a.example", "deadline": deadline})

    def test_explicit_mainland_after_hong_kong_comma(self):
        locations = (
            "Hong Kong, Shenzhen",
            "Hong Kong, Beijing",
            "Hong Kong, Mainland China",
            "Hong Kong, China / Shenzhen",
            "Hong Kong，Shenzhen",
        )
        for location in locations:
            with self.subTest(location=location):
                job, = d.fetch_jobs(GH, transport=lambda *_: {
                    "jobs": [gh_row(location={"name": location})]})
                self.assertEqual(job["region"], "both")
                manual = d.manual_job({
                    "company": "Fictional", "title": "AI Intern",
                    "url": "https://fictional.example/jobs/1", "location": location})
                self.assertEqual(manual["region"], "both")
        for location in ("Hong Kong, China", "Hong Kong, PRC", "香港，中国"):
            with self.subTest(location=location):
                self.assertEqual(d.classify_region(location), "hong_kong")

    def test_keywords_only_do_not_force_intern(self):
        self.assertEqual(d.classify_career("International Customer Support"), "other")
        self.assertEqual(d.classify_career("Customer Support", "Full-time"), "other")
        self.assertEqual(d.classify_career("2027 Graduate Software Engineer"), "graduate")
        self.assertEqual(d.classify_career("AI 實習生（應屆可投）"), "intern")
        self.assertEqual(d.classify_region(""), "unknown")
        self.assertEqual(d.classify_region("Singapore"), "other")
        self.assertEqual(d.classify_region("Hong Kong, China"), "hong_kong")


if __name__ == "__main__":
    unittest.main()
