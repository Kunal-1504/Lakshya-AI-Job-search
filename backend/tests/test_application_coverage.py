from datetime import timedelta

import httpx
import pytest
from lakshya.db.base import utc_now
from lakshya.db.models import ApplicationRecord, JobRecord
from lakshya.matcher import required_years
from lakshya.scrapers.ashby import AshbyScraper
from lakshya.scrapers.boards import employer_boards
from lakshya.scrapers.greenhouse import GreenhouseScraper
from lakshya.scrapers.lever import LeverScraper
from lakshya.services.application_policy import application_policy


def records():
    job = JobRecord(
        source="greenhouse",
        source_job_id="1",
        title="AI Engineer",
        company="Employer",
        location="Pune",
        description="Python SQL",
        remote_type="onsite",
        apply_url="https://job-boards.greenhouse.io/employer/jobs/1",
        posted_at=utc_now(),
        date_basis="published",
        match_score=90,
        is_demo=False,
        location_restrictions=[],
    )
    app = ApplicationRecord(
        status="awaiting_approval",
        critic_passed=True,
        critic_report={"passed": True},
        resume_path="resume.pdf",
    )
    return app, job


def test_policy_explains_all_observed_blockers(settings):
    settings.application_mode = "auto"
    app, job = records()
    assert application_policy(settings, app, job)["eligible"]
    job.apply_url = "https://himalayas.app/companies/example/jobs/ai-engineer"
    job.match_score = 69.86
    job.posted_at = None
    policy = application_policy(settings, app, job)
    assert not policy["eligible"] and policy["state"] == "needs_help"
    assert len(policy["reasons"]) == 3
    assert any("70%" in reason for reason in policy["reasons"])
    assert any("finish the application" in reason for reason in policy["reasons"])
    assert any("posting date" in reason for reason in policy["reasons"])


@pytest.mark.parametrize("state", ["reserved", "uncertain", "applied"])
def test_policy_never_offers_automatic_retry_for_reserved_submissions(settings, state):
    settings.application_mode = "auto"
    app, job = records()
    app.submission_state = state
    assert application_policy(settings, app, job) == {
        "eligible": False,
        "state": "finished",
        "reasons": [],
        "platform": "greenhouse",
    }


def test_policy_rejects_old_dates_unchecked_documents_and_manual_mode(settings):
    app, job = records()
    job.posted_at = utc_now() - timedelta(days=2)
    app.critic_passed = False
    reasons = application_policy(settings, app, job)["reasons"]
    assert len(reasons) == 3
    assert any("off" in reason for reason in reasons)
    assert any("accuracy" in reason for reason in reasons)


def test_submission_rechecks_experience_after_resume_preparation(settings):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from lakshya.applier import Applier
    from lakshya.services.store import as_job

    settings.application_mode = "auto"
    app, job = records()
    job.description = "5+ years of relevant engineering experience required."
    policy = application_policy(settings, app, job)
    assert not policy["eligible"]
    assert any("requires 5 years" in reason for reason in policy["reasons"])
    record = SimpleNamespace(job=as_job(job), is_demo=False, score=90)
    with pytest.raises(ValueError, match="experience preferences"):
        Applier(settings, Mock()).preflight(record, "profile-hash", auto=True, dry_run=False)


def test_starter_boards_do_not_replace_custom_lists(settings):
    assert employer_boards(settings, "greenhouse") == ["jumio", "gleanwork"]
    settings.boards = {"greenhouse": ["mycompany"]}
    assert employer_boards(settings, "greenhouse") == ["mycompany"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A minimum of 6+ years of commercial experience is required.", 6),
        ("3 years of relevant professional experience", 3),
        ("5+ years of relevant engineering experience at tech and product-driven companies", 5),
        ("2 years of hands-on experience preferred", None),
    ],
)
def test_experience_wording_preserves_user_limit(text, expected):
    assert required_years(text) == expected


def test_ashby_nullable_workplace_and_compensation_do_not_drop_jobs(settings):
    scraper = AshbyScraper(settings, None)
    rows = [
        {
            "id": "one",
            "title": "AI Engineer",
            "applyUrl": "https://jobs.ashbyhq.com/ema/one",
            "workplaceType": None,
            "isRemote": True,
            "compensation": None,
            "publishedAt": "2026-10-07T01:00:00Z",
        }
    ]
    jobs = scraper.normalize_rows(rows, lambda row: scraper.parse(row, "ema"))
    assert len(jobs) == 1 and jobs[0].remote_type == "remote"
    assert jobs[0].posted_at is not None


@pytest.mark.asyncio
async def test_greenhouse_preserves_current_publication_field_and_hosted_form(settings):
    class HTTP:
        async def get(self, url, params):
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "id": 123,
                            "title": "AI Engineer",
                            "location": {"name": "Pune"},
                            "content": "Python",
                            "absolute_url": "https://employer.example/careers?id=123",
                            "first_published": "2026-10-07T01:00:00Z",
                            "updated_at": "2026-10-08T01:00:00Z",
                        }
                    ]
                },
            )

    settings.boards = {"greenhouse": ["employer"]}
    jobs = await GreenhouseScraper(settings, HTTP()).collect()
    assert jobs[0].posted_at.day == 7
    assert jobs[0].date_basis == "first_published"
    assert str(jobs[0].apply_url) == "https://job-boards.greenhouse.io/employer/jobs/123"


@pytest.mark.asyncio
async def test_source_limit_keeps_matching_jobs_late_in_employer_feed(settings):
    class HTTP:
        async def get(self, url, params):
            rows = [
                {
                    "id": index,
                    "title": "Accountant",
                    "location": {"name": "London"},
                    "absolute_url": "https://example.com/job",
                    "content": "Accounting",
                }
                for index in range(50)
            ]
            rows.append(
                {
                    "id": 999,
                    "title": "AI Engineer",
                    "location": {"name": "Pune"},
                    "absolute_url": "https://example.com/ai",
                    "content": "Python 0-1 years experience",
                }
            )
            return httpx.Response(200, json={"jobs": rows})

    settings.max_jobs_per_source = 1
    settings.boards = {"greenhouse": ["employer"]}
    jobs = await GreenhouseScraper(settings, HTTP()).collect()
    assert len(jobs) == 1 and jobs[0].title == "AI Engineer"


def test_lever_creation_date_is_not_claimed_as_publication_date(settings):
    job = LeverScraper(settings, None).parse(
        {
            "id": "one",
            "text": "AI Engineer",
            "workplaceType": None,
            "applyUrl": "https://jobs.lever.co/netomi/one/apply",
            "createdAt": 1791334800000,
        },
        "netomi",
    )
    assert job.posted_at is None and job.date_basis == "unknown"


def test_application_next_steps_show_the_actual_unanswered_question(settings, database):
    from fastapi.testclient import TestClient
    from lakshya.api.app import create_app
    from lakshya.db.models import StatusHistory

    app, job = records()
    settings.application_mode = "auto"
    with database() as session, session.begin():
        session.add(job)
        session.flush()
        app.job_id = job.id
        app.application_key = "recruitee-question-test"
        session.add(app)
        session.flush()
        identity = app.id
        for note in (
            "unknown_fields: Do you need visa sponsorship? (save an exact answer to this question)",
            "auto_paused: Unknown, unsupported or missing fields require human input",
            "Needs your help: needs-review",
        ):
            session.add(
                StatusHistory(application_id=identity, new_status="awaiting_approval", note=note)
            )
            session.flush()
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/applications", headers={"X-API-Key": "test-api-key"})
        assert response.status_code == 200
        policy = response.json()[0]["auto_apply"]
        assert policy["state"] == "needs_help" and not policy["eligible"]
        assert policy["reasons"][0].startswith(
            "Your answers are needed: Do you need visa sponsorship?"
        )
        with database() as session, session.begin():
            session.get(ApplicationRecord, identity).submission_state = "uncertain"
        policy = client.get("/api/applications", headers={"X-API-Key": "test-api-key"}).json()[0][
            "auto_apply"
        ]
        assert policy["state"] == "finished" and not policy["reasons"]
