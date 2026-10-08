"""Idempotent, explicitly fictional seed records; no resume or application is fabricated."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.db.base import utc_now
from lakshya.db.models import ApplicationRecord, JobRecord, StatusHistory


def seed_demo(session: Session) -> int:
    added = 0
    roles = [
        ("AI Engineer", "Pune, India"),
        ("ML Engineer", "Bengaluru, India"),
        ("Data Analyst", "Remote — India"),
    ]
    for index, (role, location) in enumerate(roles, 1):
        existing = session.scalar(
            select(JobRecord).where(
                JobRecord.source == "demo", JobRecord.source_job_id == f"demo-{index}"
            )
        )
        if existing:
            continue
        job = JobRecord(
            source_job_id=f"demo-{index}",
            title=role,
            company=f"Fictional Demo Company {index}",
            location=location,
            remote_type="remote" if index == 3 else "hybrid",
            posted_at=utc_now() - timedelta(hours=index),
            source="demo",
            date_basis="demo_seed",
            description="Fictional seed job for verifying Phase 1 storage and infrastructure. "
            "This is not a real vacancy and cannot be submitted.",
            apply_url=f"https://example.invalid/demo/{index}",
            is_demo=True,
        )
        session.add(job)
        session.flush()
        application = ApplicationRecord(
            job_id=job.id,
            application_key=f"fictional demo company {index}|{role.lower()}",
            status="new",
            notes="Synthetic Phase 1 demonstration record.",
        )
        session.add(application)
        session.flush()
        session.add(
            StatusHistory(
                application_id=application.id,
                old_status=None,
                new_status="new",
                source="system",
                note="Explicit fictional demo seed",
            )
        )
        added += 1
    return added
