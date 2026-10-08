"""Submit eligible checked bundles under a candidate's enabled automatic-application policy."""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.applier import Applier, provider
from lakshya.config import Settings
from lakshya.db.models import ApplicationRecord, JobRecord
from lakshya.db.session import build_engine
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.services.application_policy import application_policy
from lakshya.services.lifecycle import transition_status
from lakshya.services.profile import load_profile
from lakshya.services.store import application_files, artifact_hash
from lakshya.tracker import Tracker


def apply_ready(settings: Settings, identities: list[str] | None = None) -> dict[str, int]:
    counts = {"applied": 0, "needs_help": 0}
    if settings.application_mode != "auto":
        return counts
    master, profile = load_profile(settings)
    engine = build_engine(settings)
    tracker = Tracker(settings)
    try:
        with Session(engine) as session:
            candidates = []
            for app, job in session.execute(
                select(ApplicationRecord, JobRecord)
                .join(JobRecord, ApplicationRecord.job_id == JobRecord.id)
                .where(ApplicationRecord.status.in_(["awaiting_approval", "approved"]))
            ):
                if identities is not None and app.id not in identities:
                    continue
                if app.submission_state or job.is_demo:
                    continue
                policy = application_policy(settings, app, job)
                # Keep this provider check explicit at the submission boundary too.
                if not policy["eligible"] or provider(job.apply_url) not in AUTO_PLATFORMS:
                    counts["needs_help"] += 1
                    continue
                candidates.append(app.id)
            candidates = candidates[
                : (
                    min(settings.max_applications_per_run, 2)
                    if __import__("os").getenv("LAKSHYA_CLOUD") == "1"
                    else settings.max_applications_per_run
                )
            ]
        for identity in candidates:
            if settings.application_mode != "auto":
                break
            try:
                with Session(engine) as session, session.begin():
                    app = session.get(ApplicationRecord, identity)
                    assert app is not None
                    if app.profile_sha256 != master.source_sha256:
                        raise ValueError("Resume changed; prepare this application again")
                    if artifact_hash(application_files(app)) != app.artifact_sha256:
                        raise ValueError("Prepared documents changed; prepare them again")
                    if app.status == "awaiting_approval":
                        transition_status(
                            session,
                            app,
                            "approved",
                            source="user",
                            human_approved=True,
                            note="Approved under the user's enabled automatic-application policy",
                        )
                result = asyncio.run(
                    Applier(settings, tracker).apply(
                        tracker.get(identity),
                        profile,
                        master.source_sha256,
                        auto=True,
                    )
                )
                if result == "applied":
                    counts["applied"] += 1
                else:
                    counts["needs_help"] += 1
                    with Session(engine) as session, session.begin():
                        app = session.get(ApplicationRecord, identity)
                        assert app is not None
                        if app.status == "approved" and not app.submission_state:
                            transition_status(
                                session, app, "awaiting_approval", note=f"Needs your help: {result}"
                            )
            except Exception as exc:
                counts["needs_help"] += 1
                with Session(engine) as session, session.begin():
                    app = session.get(ApplicationRecord, identity)
                    if app and app.status == "approved" and not app.submission_state:
                        transition_status(
                            session,
                            app,
                            "awaiting_approval",
                            note=f"Needs your help: {type(exc).__name__}",
                        )
                tracker.event(identity, "auto_paused", type(exc).__name__)
        return counts
    finally:
        tracker.close()
        engine.dispose()
