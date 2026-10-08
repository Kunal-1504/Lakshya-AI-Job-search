"""Pydantic contracts and the serializable state for the later LangGraph workflow."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ApplicationStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    RESUME_READY = "resume_ready"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    VIEWED = "viewed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"
    SKIPPED = "skipped"


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Job(StrictSchema):
    source_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str = "Unknown"
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    posted_at: datetime | None = None
    description: str
    apply_url: HttpUrl
    source: str = Field(min_length=1)
    salary: str | None = None
    date_basis: str = "unknown"
    location_restrictions: list[str] = Field(default_factory=list)

    @field_validator("posted_at")
    @classmethod
    def utc_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Posting date must include a timezone; never guess freshness")
        return value.astimezone(UTC) if value is not None else None


class Contact(StrictSchema):
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class EvidenceFact(StrictSchema):
    id: str
    section: Literal["summary", "skills", "projects", "education", "experience", "other"]
    text: str = Field(min_length=1)
    source_excerpt: str = Field(min_length=1)
    context_id: str | None = None


class MasterProfile(StrictSchema):
    schema_version: int = 1
    contact: Contact
    skills: list[str]
    projects: list[str]
    education: list[str]
    experience: list[str]
    keywords: list[str]
    strengths: list[str]
    facts: list[EvidenceFact]
    raw_text: str
    source_sha256: str
    search_queries: list[str] = Field(default_factory=list)
    role_variants: list[str] = Field(default_factory=list)
    location_variants: list[str] = Field(default_factory=list)


class JDAnalysis(StrictSchema):
    required_skills: list[str]
    preferred_skills: list[str]
    min_years: float | None = Field(default=None, ge=0)
    seniority: str
    tech_stack: list[str]
    red_flags: list[str]
    location_eligible: bool | None = None


class MatchResult(StrictSchema):
    score: float = Field(ge=0, le=100)
    semantic_score: float = Field(ge=0, le=100)
    skill_score: float = Field(ge=0, le=100)
    title_score: float = Field(ge=0, le=100)
    llm_judgment_score: float = Field(ge=0, le=100)
    matched_skills: list[str]
    missing_skills: list[str]
    reasoning: str
    shortlisted: bool
    exclusion_reasons: list[str]


class CriticReport(StrictSchema):
    passed: bool
    score: float = Field(ge=0, le=100)
    unsupported_claims: list[str]
    missing_keywords: list[str]
    formatting_issues: list[str]
    typos: list[str]
    artifact_sha256: str


class AgentInput(StrictSchema):
    run_id: str
    job_id: str | None = None
    iteration: int = Field(default=1, ge=1, le=3)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(StrictSchema):
    ok: bool
    decision: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class WorkflowState(TypedDict, total=False):
    run_id: str
    profile_sha256: str
    jobs: list[dict[str, Any]]
    current_job_id: str | None
    analysis: dict[str, Any]
    match: dict[str, Any]
    files: dict[str, str]
    critic: dict[str, Any]
    tailor_round: int
    approval: dict[str, Any] | None
    dry_run: bool
    auto: bool
    errors: list[str]
    token_count: int
    cost_usd: float
