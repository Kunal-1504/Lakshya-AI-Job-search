"""Explain automatic submission eligibility without hiding unhandled applications."""

from typing import Any

from lakshya import applier
from lakshya.config import Settings
from lakshya.db.models import ApplicationRecord, JobRecord
from lakshya.matcher import location_allowed, required_years, role_allowed
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.services.store import as_job
from lakshya.utils import is_fresh


def application_policy(
    settings: Settings, app: ApplicationRecord, job: JobRecord
) -> dict[str, Any]:
    platform = applier.provider(job.apply_url)
    if app.submission_state or app.status in {
        "applied",
        "viewed",
        "interview_scheduled",
        "offer",
        "rejected",
        "withdrawn",
        "skipped",
    }:
        return {"eligible": False, "state": "finished", "reasons": [], "platform": platform}
    reasons = []
    normalized = as_job(job)
    if not role_allowed(normalized, settings) or not location_allowed(normalized, settings):
        reasons.append("This opening does not meet your current role or location preferences.")
    years = required_years(job.description)
    if years is not None and years > settings.max_experience_years:
        reasons.append(
            f"This opening requires {years:g} years of experience; your maximum is {settings.max_experience_years:g}."
        )
    if settings.application_mode != "auto":
        reasons.append(
            "Automatic applications are off. Choose Apply automatically in My preferences."
        )
    if job.is_demo:
        reasons.append("This is a test listing and cannot be submitted.")
    if platform not in AUTO_PLATFORMS:
        reasons.append(
            "This website needs you to finish the application. Download your resume and open the job link."
        )
    if job.match_score is None:
        reasons.append("Prepare this job first so its fit can be checked.")
    elif job.match_score < 80:
        reasons.append(
            f"Fit is {job.match_score:.0f}%. Automatic applications require at least 80%; you can still apply yourself."
        )
    if not is_fresh(as_job(job), settings.freshness_hours):
        reasons.append(
            "The posting date is unknown or outside your 24-hour window. Check that the employer is still hiring."
        )
    if not app.critic_passed or not app.critic_report.get("passed") or not app.resume_path:
        reasons.append("A tailored resume must pass its accuracy checks before submission.")
    if app.status not in {"awaiting_approval", "approved"}:
        reasons.append("Resume preparation has not finished or this application needs review.")
    return {
        "eligible": not reasons,
        "state": "needs_help" if reasons else "ready",
        "reasons": reasons,
        "platform": platform,
    }
