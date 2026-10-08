from sqlalchemy.orm import Session

from lakshya.db.base import utc_now
from lakshya.db.models import ApplicationRecord, StatusHistory
from lakshya.schemas import ApplicationStatus

TRANSITIONS: dict[str, set[str]] = {
    "new": {"shortlisted", "skipped", "failed"},
    "shortlisted": {"resume_ready", "skipped", "failed"},
    "resume_ready": {"awaiting_approval", "needs_human_review", "failed"},
    "needs_human_review": {"resume_ready", "skipped", "failed"},
    "awaiting_approval": {"approved", "resume_ready", "skipped", "failed"},
    "approved": {"applying", "awaiting_approval", "skipped", "failed"},
    "applying": {"applied", "failed"},
    "applied": {"viewed", "interview_scheduled", "rejected", "withdrawn"},
    "viewed": {"interview_scheduled", "rejected", "withdrawn"},
    "interview_scheduled": {"offer", "rejected", "withdrawn"},
    "offer": {"withdrawn"},
    "rejected": set(),
    "withdrawn": set(),
    "failed": {"new", "resume_ready", "skipped"},
    "skipped": set(),
}


def transition_status(
    session: Session,
    application: ApplicationRecord,
    new: ApplicationStatus | str,
    *,
    source: str = "system",
    note: str = "",
    human_approved: bool = False,
) -> None:
    """Called inside one transaction; state and audit history either both commit or both roll back."""
    new = ApplicationStatus(new)
    old = application.status
    if new.value not in TRANSITIONS.get(old, set()):
        raise ValueError(f"Invalid status transition: {old} -> {new.value}")
    if new in {
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.APPROVED,
        ApplicationStatus.APPLYING,
    }:
        if (
            not application.critic_passed
            or not application.artifact_sha256
            or not application.critic_report.get("passed")
        ):
            raise ValueError("A passing Critic report bound to the generated artifact is required")
        if application.critic_report.get("artifact_sha256") != application.artifact_sha256:
            raise ValueError("Critic report does not match the current generated artifact")
    if new == ApplicationStatus.APPROVED:
        if not human_approved or source != "user":
            raise ValueError("Explicit human approval is required")
        application.approved_artifact_sha256 = application.artifact_sha256
        application.approved_at = utc_now()
    if new == ApplicationStatus.APPLYING:
        if application.approved_artifact_sha256 != application.artifact_sha256:
            raise ValueError("The generated artifact changed after approval")
    if old == "failed" and application.submission_state in {"reserved", "uncertain", "applied"}:
        raise ValueError("A submission with an uncertain outcome must be resolved before retry")
    if new in {
        ApplicationStatus.RESUME_READY,
        ApplicationStatus.AWAITING_APPROVAL,
        ApplicationStatus.SKIPPED,
    }:
        application.approved_at = None
        application.approved_artifact_sha256 = None
    application.status = new.value
    application.updated_at = utc_now()
    if new == ApplicationStatus.APPLIED:
        application.applied_at = utc_now()
    session.add(
        StatusHistory(
            application_id=application.id,
            old_status=old,
            new_status=new.value,
            source=source,
            note=note,
        )
    )
