"""Validated interchange models shared by collectors and pipeline stages."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Status(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    RESUME_READY = "resume_ready"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    PREPARED = "awaiting_approval"
    APPROVED = "approved"
    APPLYING = "applying"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    VIEWED = "viewed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Job(BaseModel):
    id: str
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str = "Unknown"
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    posted_at: datetime | None = None
    description: str = ""
    apply_url: HttpUrl
    source: str
    salary: str | None = None
    source_url: str | None = None
    date_basis: str = "unknown"
    location_restrictions: list[str] = Field(default_factory=list)

    @field_validator("posted_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return None


class Contact(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class Fact(BaseModel):
    id: str
    section: Literal["summary", "skills", "projects", "education", "experience", "other"]
    text: str


class Profile(BaseModel):
    schema_version: int = 1
    contact: Contact
    skills: list[str]
    projects: list[str]
    education: list[str]
    experience: list[str]
    keywords: list[str]
    facts: list[Fact]
    raw_text: str
    source_file: str
    strengths: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class JDAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_skills: list[str]
    missing_skills: list[str]
    seniority: str
    min_years: float | None = Field(default=None, ge=0)
    location_eligible: bool | None = None
    location_reason: str = ""
    preferred_skills: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    reasoning: str = ""
    fit_judgment: float = Field(default=50, ge=0, le=100)


class MatchResult(BaseModel):
    score: float = Field(ge=0, le=100)
    semantic_score: float
    skill_score: float
    role_score: float
    analysis: JDAnalysis
    shortlisted: bool
    reasons: list[str]
    backend: str


class TailorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(min_length=1, max_length=32)
    skill_order: list[str]
    reasons: list[str]
