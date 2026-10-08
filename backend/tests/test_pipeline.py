from datetime import timedelta

import pytest
from docx import Document
from lakshya.agents.critic import review_bundle
from lakshya.db.base import utc_now
from lakshya.db.models import AgentRun, ApplicationRecord, BudgetReservation, JobRecord, PipelineRun
from lakshya.deduplication import deduplicate
from lakshya.matcher import Matcher, location_allowed, required_years
from lakshya.models import Job
from lakshya.pipeline import Pipeline
from lakshya.services.profile import import_profile, load_profile
from lakshya.services.store import application_files, as_job
from lakshya.tools.budget import Budget
from lakshya.tracker import Tracker
from sqlalchemy import select


@pytest.fixture
def completed(settings, database):
    pipeline = Pipeline(settings)
    run_id = pipeline.start({"demo": True, "offline": True, "dry_run": True})
    result = pipeline.execute(run_id)
    yield pipeline, run_id, result
    pipeline.close()


def test_full_demo_is_reviewed_and_never_submitted(completed, database):
    pipeline, identity, result = completed
    assert len(result["ready"]) == 3
    with database() as session:
        rows = list(session.scalars(select(ApplicationRecord)))
        assert all(r.critic_passed and r.status == "awaiting_approval" for r in rows)
        assert all(not r.applied_at and not r.submission_state for r in rows)
        assert session.get(PipelineRun, identity).status == "completed"
        names = {r.agent_name for r in session.scalars(select(AgentRun))}
        assert {
            "profile",
            "scout:demo",
            "dedup",
            "jd_analyst",
            "matcher",
            "tailor",
            "critic",
            "tracker",
            "followup",
        } <= names
        assert session.scalar(select(BudgetReservation)) is None


def test_critic_rejects_planted_fabrication(completed, settings, database):
    _, _, result = completed
    _, profile = load_profile(settings, True)
    with database() as session:
        app = session.get(ApplicationRecord, result["ready"][0])
        job = as_job(session.get(JobRecord, app.job_id))
        files = application_files(app)
    document = Document(files["docx"])
    document.add_paragraph("Led 50 engineers at Google and increased revenue by 300 percent.")
    document.save(files["docx"])
    report = review_bundle(profile, job, files)
    assert not report.passed
    assert "Google" in report.unsupported_claims[0]
    assert "PDF and DOCX content differ" in report.formatting_issues


def test_graph_interrupt_survives_reopen(settings, database):
    # Use an explicitly configured fictional non-submitting run to exercise the real interrupt.
    pipeline = Pipeline(settings)
    identity = pipeline.start({"demo": True, "offline": True, "dry_run": False})
    result = pipeline.execute(identity)
    assert result["__interrupt__"][0].value["kind"] == "approval"
    ready = result["ready"]
    pipeline.close()
    reopened = Pipeline(settings)
    try:
        result = reopened.execute(identity, {app: "reject" for app in ready})
        assert "__interrupt__" not in result
        with database() as session:
            assert all(session.get(ApplicationRecord, app).status == "skipped" for app in ready)
    finally:
        reopened.close()


def test_profile_cache_is_hash_based_and_demo_is_separate(settings, tmp_path):
    master, _ = load_profile(settings, True)
    assert not (settings.data_dir / "master_profile.json").exists()
    path = tmp_path / "resume.txt"
    path.write_text(
        "Real Candidate\nSummary\nBuilt Python academic projects.\nSkills\nPython, SQL\nEducation\nB.Tech 2025"
    )
    first = import_profile(path, settings)
    target = settings.data_dir / "master_profile.json"
    timestamp = target.stat().st_mtime_ns
    assert import_profile(path, settings).source_sha256 == first.source_sha256
    assert target.stat().st_mtime_ns == timestamp
    path.write_text(path.read_text() + "\nNew documented project")
    assert import_profile(path, settings).source_sha256 != first.source_sha256
    assert master.source_sha256 != first.source_sha256


def listing(**changes):
    data = dict(
        id="one",
        title="AI Engineer",
        company="Example Private Limited",
        location="Pune",
        description="Python SQL. 0-1 years experience.",
        posted_at=utc_now(),
        apply_url="https://example.invalid/jobs/one",
        source="demo",
    )
    return Job.model_validate(data | changes)


def test_cloud_matches_later_jobs_before_limiting_tailoring(settings, database, monkeypatch):
    from types import SimpleNamespace

    pipeline = Pipeline(settings)
    monkeypatch.setenv("LAKSHYA_CLOUD", "1")
    monkeypatch.setattr(pipeline, "agent", lambda state, name, work, *args: work(None))
    scores = {"first": 68, "second": 70, "third": 95}

    class MatcherStub:
        def __init__(self, *args):
            pass

        def analyze(self, profile, job):
            from lakshya.models import JDAnalysis

            return JDAnalysis(required_skills=[], missing_skills=[], seniority="entry")

        def match(self, profile, job, analysis):
            result = {
                "score": scores[job.id],
                "analysis": {"missing_skills": [], "required_skills": []},
                "semantic_score": 80,
                "skill_score": 80,
                "role_score": 80,
                "shortlisted": True,
                "reasons": [],
            }
            return SimpleNamespace(model_dump=lambda **kwargs: result)

    monkeypatch.setattr("lakshya.pipeline.Matcher", MatcherStub)
    state = {
        "options": {"demo": True, "auto": True},
        "jobs": [
            listing(
                id=identity,
                company=identity + " Employer",
                apply_url="https://jobs.lever.co/employer/" + identity,
            ).model_dump(mode="json")
            for identity in scores
        ],
    }
    try:
        result = pipeline.match(state)
        assert len(result["applications"]) == 2
        with database() as session:
            assert len(list(session.scalars(select(JobRecord)))) == 3
            first = session.get(ApplicationRecord, result["applications"][0])
            assert session.get(JobRecord, first.job_id).source_job_id == "third"
    finally:
        pipeline.close()


def test_dedup_and_eligibility_gates(settings):
    one = listing()
    duplicate = listing(
        id="two", company="Example Pvt Ltd", apply_url="https://example.invalid/jobs/two"
    )
    senior = listing(
        id="three", title="Senior AI Engineer", apply_url="https://example.invalid/jobs/three"
    )
    assert len(deduplicate([one, duplicate, senior])) == 2
    assert not location_allowed(
        listing(location="Remote US", remote_type="remote", location_restrictions=["US"]), settings
    )
    assert required_years("3 years experience preferred") is None
    assert required_years("over 2 years of experience") > 2
    _, profile = load_profile(settings, True)
    matcher = Matcher(settings, similarity=lambda a, b: 1)
    assert not matcher.match(profile, listing(posted_at=None)).shortlisted
    assert not matcher.match(
        profile, listing(posted_at=utc_now() - timedelta(hours=25))
    ).shortlisted
    assert not matcher.match(profile, senior).shortlisted


def test_budget_retains_failed_reservations_and_enforces_cap(settings, database):
    pipeline = Pipeline(settings)
    run = pipeline.start({"dry_run": True})
    with database() as session, session.begin():
        agent = AgentRun(run_id=run, agent_name="test")
        session.add(agent)
        session.flush()
        identity = agent.id
    settings.max_run_tokens = 10
    budget = Budget(pipeline.engine, settings, run, identity)
    first = budget.reserve(8, 0.01)
    with pytest.raises(ValueError, match="budget"):
        budget.reserve(3, 0.01)
    budget.settle(first, 1, 0.001)
    budget.reserve(3, 0.01)
    pipeline.close()


def test_changed_artifact_and_duplicate_reservations_are_blocked(completed, settings, database):
    from lakshya.services.lifecycle import transition_status

    _, _, result = completed
    identity = result["ready"][0]
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, identity)
        transition_status(session, app, "approved", source="user", human_approved=True)
        profile_hash = app.profile_sha256
    tracker = Tracker(settings)
    try:
        record = tracker.get(identity)
        tracker.verify_approval(record, profile_hash)
        tracker.reserve(record.job, settings.daily_application_cap, settings.timezone)
        with pytest.raises(ValueError, match="Duplicate"):
            tracker.reserve(record.job, settings.daily_application_cap, settings.timezone)
        tracker.finish_submission(record.job, False)
        with database() as session:
            app = session.get(ApplicationRecord, identity)
            assert app.status == "failed" and app.submission_state == "uncertain"
    finally:
        tracker.close()
