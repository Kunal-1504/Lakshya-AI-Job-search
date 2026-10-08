import pytest
from lakshya.db.models import ApplicationRecord, StatusHistory
from lakshya.db.seed import seed_demo
from lakshya.schemas import ApplicationStatus as Status
from lakshya.services.lifecycle import transition_status
from sqlalchemy import func, select


def seeded_application(database):
    with database() as session, session.begin():
        seed_demo(session)
        application = session.scalar(select(ApplicationRecord))
        return application.id


def test_status_and_history_commit_together(database):
    application_id = seeded_application(database)
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, application_id)
        transition_status(session, app, Status.SHORTLISTED, source="agent", note="Qualified")
    with database() as session:
        history = list(
            session.scalars(
                select(StatusHistory).where(StatusHistory.application_id == application_id)
            )
        )
        assert session.get(ApplicationRecord, application_id).status == "shortlisted"
        assert len(history) == 2
        assert history[-1].old_status == "new"
        assert history[-1].note == "Qualified"
    with (
        pytest.raises(ValueError, match="Invalid status transition"),
        database() as session,
        session.begin(),
    ):
        app = session.get(ApplicationRecord, application_id)
        transition_status(session, app, Status.APPLIED, source="user")


def test_critic_and_explicit_approval_cannot_be_bypassed(database):
    application_id = seeded_application(database)
    with database() as session, session.begin():
        app = session.get(ApplicationRecord, application_id)
        transition_status(session, app, Status.SHORTLISTED, source="agent")
        transition_status(session, app, Status.RESUME_READY, source="agent")
        with pytest.raises(ValueError, match="passing Critic"):
            transition_status(session, app, Status.AWAITING_APPROVAL, source="agent")
        app.critic_passed = True
        app.artifact_sha256 = "a" * 64
        app.critic_report = {"passed": True, "artifact_sha256": "a" * 64}
        transition_status(session, app, Status.AWAITING_APPROVAL, source="agent")
        with pytest.raises(ValueError, match="human approval"):
            transition_status(session, app, Status.APPROVED, source="agent")
        transition_status(session, app, Status.APPROVED, source="user", human_approved=True)
        app.artifact_sha256 = "b" * 64
        app.critic_report = {"passed": True, "artifact_sha256": "b" * 64}
        with pytest.raises(ValueError, match="changed after approval"):
            transition_status(session, app, Status.APPLYING, source="agent")


def test_transaction_rollback_removes_status_and_history(database):
    application_id = seeded_application(database)
    with pytest.raises(RuntimeError), database() as session, session.begin():
        app = session.get(ApplicationRecord, application_id)
        transition_status(session, app, Status.SHORTLISTED, source="agent")
        raise RuntimeError("failure before commit")
    with database() as session:
        assert session.get(ApplicationRecord, application_id).status == "new"
        assert (
            session.scalar(
                select(func.count())
                .select_from(StatusHistory)
                .where(StatusHistory.application_id == application_id)
            )
            == 1
        )
