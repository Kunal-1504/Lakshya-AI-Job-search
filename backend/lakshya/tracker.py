"""Application assistant adapter with atomic daily reservations and uncertainty blocking."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.config import Settings
from lakshya.db.base import utc_now
from lakshya.db.models import ApplicationRecord, StatusHistory
from lakshya.db.models import JobRecord as StoredJob
from lakshya.db.session import build_engine
from lakshya.models import Job
from lakshya.services.lifecycle import transition_status
from lakshya.services.store import application_files, artifact_hash, as_job


@dataclass
class JobRecord:
    id: str
    application_id: str
    job: Job
    score: float | None
    files: dict[str, str]
    is_demo: bool


def job_from(row: JobRecord) -> Job:
    return row.job


class Tracker:
    def __init__(self, settings: Settings) -> None:
        self.settings, self.engine = settings, build_engine(settings)

    def get(self, identity: str) -> JobRecord:
        with Session(self.engine) as session:
            application = session.get(ApplicationRecord, identity)
            if application is None:
                application = session.scalar(
                    select(ApplicationRecord)
                    .join(StoredJob, ApplicationRecord.job_id == StoredJob.id)
                    .where(StoredJob.source + ":" + StoredJob.source_job_id == identity)
                )
            if not application:
                raise ValueError("Application not found")
            job = session.get(StoredJob, application.job_id)
            assert job is not None
            return JobRecord(
                id=as_job(job).id,
                application_id=application.id,
                job=as_job(job),
                score=job.match_score,
                files=application_files(application),
                is_demo=job.is_demo,
            )

    def verify_approval(self, record: JobRecord, profile_hash: str) -> None:
        with Session(self.engine) as session:
            app = session.get(ApplicationRecord, record.application_id)
            assert app is not None
            if (
                app.status != "approved"
                or not app.critic_passed
                or not app.critic_report.get("passed")
            ):
                raise ValueError("Approve the passing critic bundle before applying")
            digest = artifact_hash(record.files)
            if digest != app.artifact_sha256 or digest != app.approved_artifact_sha256:
                raise ValueError("Artifacts changed after review; regenerate and review again")
            if profile_hash != app.profile_sha256:
                raise ValueError("Master resume changed after review")
            if app.submission_state:
                raise ValueError("Application already reserved or sent; automatic retry forbidden")

    def reserve(self, job: Job, cap: int, timezone: str) -> None:
        day = datetime.now(ZoneInfo(timezone)).date()
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(73493212)")
            try:
                with Session(bind=connection) as session:
                    rows = list(session.scalars(select(ApplicationRecord)))
                    counted = [
                        r
                        for r in rows
                        if r.submission_state in {"reserved", "uncertain", "applied"}
                        and (r.applied_at or r.updated_at).astimezone(ZoneInfo(timezone)).date()
                        == day
                    ]
                    if len(counted) >= cap:
                        raise ValueError("Daily application cap reached")
                    app = session.scalar(
                        select(ApplicationRecord)
                        .join(StoredJob, ApplicationRecord.job_id == StoredJob.id)
                        .where(
                            StoredJob.source == job.source,
                            StoredJob.source_job_id == job.id.removeprefix(job.source + ":"),
                        )
                    )
                    assert app is not None
                    if app.submission_state or app.status != "approved":
                        raise ValueError("Duplicate submission reservation rejected")
                    self.verify_approval(self.get(app.id), app.profile_sha256 or "")
                    transition_status(
                        session, app, "applying", note="Reserved before browser submit"
                    )
                    app.submission_state = "reserved"
                    session.flush()
                connection.commit()
                # Persist the reservation to cloud storage BEFORE any browser POST.
                from lakshya.cloud.store import flush

                flush(self.settings.data_dir)
            except Exception:
                connection.rollback()
                raise

    def finish_submission(self, job: Job, confirmed: bool) -> None:
        with Session(self.engine) as session, session.begin():
            app = session.scalar(
                select(ApplicationRecord)
                .join(StoredJob, ApplicationRecord.job_id == StoredJob.id)
                .where(
                    StoredJob.source == job.source,
                    StoredJob.source_job_id == job.id.removeprefix(job.source + ":"),
                )
            )
            assert app is not None
            app.submission_state = "applied" if confirmed else "uncertain"
            transition_status(
                session,
                app,
                "applied" if confirmed else "failed",
                note="Submission confirmed" if confirmed else "Outcome uncertain; do not retry",
            )
            if confirmed:
                from datetime import timedelta

                app.follow_up_date = utc_now() + timedelta(days=self.settings.follow_up_days)

    def event(self, identity: str, kind: str, message: str) -> None:
        record = self.get(identity)
        with Session(self.engine) as session, session.begin():
            app = session.get(ApplicationRecord, record.application_id)
            assert app is not None
            session.add(
                StatusHistory(
                    application_id=app.id,
                    old_status=app.status,
                    new_status=app.status,
                    source="application",
                    note=f"{kind}: {message}",
                )
            )

    def close(self) -> None:
        self.engine.dispose()
