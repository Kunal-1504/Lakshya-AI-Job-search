"""Database projections, event logging and artifact integrity."""

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.db.models import AgentEvent, ApplicationRecord, JobRecord, StatusHistory
from lakshya.deduplication import application_key
from lakshya.models import Job


def as_job(row: JobRecord) -> Job:
    return Job(
        id=f"{row.source}:{row.source_job_id}",
        title=row.title,
        company=row.company,
        location=row.location,
        remote_type=row.remote_type,
        posted_at=row.posted_at,
        description=row.description,
        apply_url=row.apply_url,
        source=row.source,
        salary=row.salary,
        date_basis=row.date_basis,
        location_restrictions=row.location_restrictions,
    )


def save_job(session: Session, job: Job, demo: bool = False) -> tuple[JobRecord, ApplicationRecord]:
    source_id = job.id.removeprefix(job.source + ":")
    row = session.scalar(
        select(JobRecord).where(
            JobRecord.source == job.source, JobRecord.source_job_id == source_id
        )
    )
    if row is None:
        data = job.model_dump(mode="python", exclude={"id", "source_url"})
        data["apply_url"] = str(job.apply_url)
        row = JobRecord(**data, source_job_id=source_id, is_demo=demo)
        session.add(row)
        session.flush()
    application = session.scalar(
        select(ApplicationRecord).where(ApplicationRecord.application_key == application_key(job))
    )
    if application is None:
        application = ApplicationRecord(job_id=row.id, application_key=application_key(job))
        session.add(application)
        session.flush()
        session.add(
            StatusHistory(
                application_id=application.id,
                old_status=None,
                new_status="new",
                note="Discovered listing",
            )
        )
    return row, application


def event(
    session: Session,
    run_id: str,
    step: str,
    message: str,
    payload: dict[str, Any] | None = None,
    agent_run_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    session.add(
        AgentEvent(
            run_id=run_id,
            step=step,
            message=message,
            payload=payload or {},
            agent_run_id=agent_run_id,
            tool_name=tool_name,
        )
    )


def artifact_hash(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key in sorted(files):
        digest.update(key.encode())
        digest.update(Path(files[key]).read_bytes())
    return digest.hexdigest()


def application_files(row: ApplicationRecord) -> dict[str, str]:
    if not row.resume_path:
        raise ValueError("No resume bundle exists")
    folder = Path(row.resume_path).parent
    return {
        key: str(folder / name)
        for key, name in {
            "pdf": "resume.pdf",
            "docx": "resume.docx",
            "cover_note": "cover_note.txt",
            "report": "changes_report.md",
            "text": "resume.txt",
            "plan": "tailor_plan.json",
        }.items()
    }


def public_row(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
