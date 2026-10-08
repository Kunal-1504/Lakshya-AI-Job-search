"""foundations

Revision ID: 0001_foundations
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_foundations"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("remote_type", sa.String(length=20), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("salary", sa.String(length=255), nullable=True),
        sa.Column("date_basis", sa.String(length=50), nullable=False),
        sa.Column("location_restrictions", sa.JSON(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("matched_skills", sa.JSON(), nullable=False),
        sa.Column("missing_skills", sa.JSON(), nullable=False),
        sa.Column("jd_analysis", sa.JSON(), nullable=False),
        sa.Column("match_reasoning", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "remote_type IN ('onsite','hybrid','remote','unknown')",
            name=op.f("ck_jobs_remote_type"),
        ),
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 100)",
            name=op.f("ck_jobs_score_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("source", "source_job_id", name=op.f("uq_jobs_source")),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_jobs_match_score"), ["match_score"], unique=False)
        batch_op.create_index(batch_op.f("ix_jobs_source"), ["source"], unique=False)

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("graph_thread_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("auto", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_control", sa.String(length=20), nullable=True),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
        sa.UniqueConstraint("graph_thread_id", name=op.f("uq_pipeline_runs_graph_thread_id")),
    )
    with op.batch_alter_table("pipeline_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pipeline_runs_status"), ["status"], unique=False)

    op.create_table(
        "screening_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_answers")),
        sa.UniqueConstraint("question", name=op.f("uq_screening_answers_question")),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_agent_runs_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_runs_agent_name"), ["agent_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_agent_runs_run_id"), ["run_id"], unique=False)

    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("application_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("resume_path", sa.Text(), nullable=True),
        sa.Column("docx_path", sa.Text(), nullable=True),
        sa.Column("cover_note_path", sa.Text(), nullable=True),
        sa.Column("changes_report_path", sa.Text(), nullable=True),
        sa.Column("critic_report", sa.JSON(), nullable=False),
        sa.Column("critic_passed", sa.Boolean(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("profile_sha256", sa.String(length=64), nullable=True),
        sa.Column("approved_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_method", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("follow_up_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_draft", sa.Text(), nullable=True),
        sa.Column("follow_up_approved", sa.Boolean(), nullable=False),
        sa.Column("submission_state", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('new','shortlisted','resume_ready','needs_human_review','awaiting_approval','approved','applying','applied','viewed','interview_scheduled','offer','rejected','withdrawn','failed','skipped')",
            name=op.f("ck_applications_status_value"),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_applications_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.UniqueConstraint("application_key", name=op.f("uq_applications_application_key")),
        sa.UniqueConstraint("job_id", name=op.f("uq_applications_job_id")),
    )
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_applications_status"), ["status"], unique=False)

    op.create_table(
        "agent_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("step", sa.String(length=50), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_events_agent_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_agent_events_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
    )
    with op.batch_alter_table("agent_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_events_run_id"), ["run_id"], unique=False)

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("local_day", sa.String(length=10), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_usd", sa.Float(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reserved_tokens >= 0 AND reserved_cost_usd >= 0",
            name=op.f("ck_budget_reservations_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_budget_reservations_agent_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline_runs.id"],
            name=op.f("fk_budget_reservations_run_id_pipeline_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_reservations")),
    )
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_budget_reservations_local_day"), ["local_day"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_budget_reservations_run_id"), ["run_id"], unique=False)

    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("old_status", sa.String(length=40), nullable=True),
        sa.Column("new_status", sa.String(length=40), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_status_history_application_id_applications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_history")),
    )
    with op.batch_alter_table("status_history", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_status_history_application_id"), ["application_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("status_history", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_status_history_application_id"))

    op.drop_table("status_history")
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_budget_reservations_run_id"))
        batch_op.drop_index(batch_op.f("ix_budget_reservations_local_day"))

    op.drop_table("budget_reservations")
    with op.batch_alter_table("agent_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_events_run_id"))

    op.drop_table("agent_events")
    with op.batch_alter_table("applications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_applications_status"))

    op.drop_table("applications")
    with op.batch_alter_table("agent_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_runs_run_id"))
        batch_op.drop_index(batch_op.f("ix_agent_runs_agent_name"))

    op.drop_table("agent_runs")
    op.drop_table("screening_answers")
    with op.batch_alter_table("pipeline_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_status"))

    op.drop_table("pipeline_runs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_source"))
        batch_op.drop_index(batch_op.f("ix_jobs_match_score"))

    op.drop_table("jobs")
