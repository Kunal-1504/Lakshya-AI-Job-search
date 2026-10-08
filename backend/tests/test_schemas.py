from datetime import UTC, datetime

import pytest
from lakshya.schemas import AgentInput, ApplicationStatus, Job
from pydantic import ValidationError


def data():
    return {
        "source_job_id": "1",
        "title": "AI Engineer",
        "company": "Demo",
        "description": "Synthetic description",
        "apply_url": "https://example.invalid/job",
        "source": "demo",
    }


def test_dates_are_aware_and_urls_validated():
    job = Job(**data(), posted_at=datetime.now(UTC))
    assert job.posted_at.tzinfo == UTC
    with pytest.raises(ValidationError, match="timezone"):
        Job(**data(), posted_at=datetime(2026, 10, 5))
    invalid = {**data(), "apply_url": "javascript:alert(1)"}
    with pytest.raises(ValidationError):
        Job(**invalid)


def test_agent_iteration_cap_and_lifecycle_contract():
    with pytest.raises(ValidationError):
        AgentInput(run_id="test", iteration=4)
    assert ApplicationStatus.AWAITING_APPROVAL.value == "awaiting_approval"
