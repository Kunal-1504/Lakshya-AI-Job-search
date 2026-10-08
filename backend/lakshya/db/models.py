from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lakshya.db.base import Base, UTCDateTime, utc_now
from lakshya.schemas import ApplicationStatus

STATUS_VALUES = ",".join(repr(status.value) for status in ApplicationStatus)


def new_id() -> str:
    return str(uuid4())


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id"),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 100)", name="score_range"
        ),
        CheckConstraint(
            "remote_type IN ('onsite','hybrid','remote','unknown')", name="remote_type"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_job_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str] = mapped_column(String(255), default="Unknown")
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown")
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    apply_url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), index=True)
    salary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_basis: Mapped[str] = mapped_column(String(50), default="unknown")
    location_restrictions: Mapped[list[str]] = mapped_column(JSON, default=list)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    jd_analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    match_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ApplicationRecord(Base):
    __tablename__ = "applications"
    __table_args__ = (CheckConstraint(f"status IN ({STATUS_VALUES})", name="status_value"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    application_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(40), default=ApplicationStatus.NEW.value, index=True)
    resume_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    docx_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_note_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    changes_report_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    critic_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    critic_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    apply_method: Mapped[str] = mapped_column(String(20), default="assist")
    notes: Mapped[str] = mapped_column(Text, default="")
    follow_up_date: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    follow_up_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    submission_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class StatusHistory(Base):
    __tablename__ = "status_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str] = mapped_column(String(40))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    source: Mapped[str] = mapped_column(String(30), default="system")
    note: Mapped[str] = mapped_column(Text, default="")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    graph_thread_id: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    requested_control: Mapped[str | None] = mapped_column(String(20), nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(50), index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    step: Mapped[str] = mapped_column(String(50))
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ScreeningAnswer(Base):
    __tablename__ = "screening_answers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    question: Mapped[str] = mapped_column(Text, unique=True)
    answer: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint("reserved_tokens >= 0 AND reserved_cost_usd >= 0", name="nonnegative"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    local_day: Mapped[str] = mapped_column(String(10), index=True)
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    reserved_cost_usd: Mapped[float] = mapped_column(Float)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="reserved")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
