"""Authenticated application API, file downloads, background runs and SSE events."""

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from lakshya.cloud import store as cloud
from lakshya.config import Settings
from lakshya.db.base import utc_now
from lakshya.db.models import (
    AgentEvent,
    AgentRun,
    ApplicationRecord,
    JobRecord,
    PipelineRun,
    ScreeningAnswer,
    StatusHistory,
)
from lakshya.matcher import role_allowed
from lakshya.pipeline import Pipeline
from lakshya.schemas import ApplicationStatus, MasterProfile
from lakshya.services.exports import draft_followups, export_excel
from lakshya.services.lifecycle import transition_status
from lakshya.services.profile import import_profile, load_profile, profile_status
from lakshya.services.readiness import readiness
from lakshya.services.store import application_files, artifact_hash, as_job, public_row


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demo: bool = False
    offline: bool = False
    dry_run: bool = False
    auto: bool = False
    stage: Literal["all", "scout", "match", "tailor"] = "all"


class StatusRequest(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = Field(default=None, max_length=20000)
    note: str = Field(default="", max_length=2000)
    expected_status: str | None = None


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=10000)


class CredentialRequest(BaseModel):
    provider: Literal["anthropic", "gemini", "adzuna_app_id", "adzuna_app_key"]
    value: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.-]+$")


class RunManager:
    """One pipeline worker avoids concurrent checkpoint/artifact overwrites."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self.settings, self.factory = settings, factory
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lakshya-pipeline")
        self.active: set[str] = set()
        self.lock = threading.RLock()
        self.scheduler = BackgroundScheduler(timezone=settings.timezone)
        self.next_search_at = utc_now()
        self.last_scheduled_run: str | None = None
        self.scheduler_error: str | None = None

    def start_scheduler(self) -> None:
        if cloud.enabled():
            return
        if self.settings.live_search_enabled:
            # A process restart cannot resume the previous worker thread implicitly.
            with self.factory() as session, session.begin():
                for run in session.scalars(
                    select(PipelineRun).where(PipelineRun.status.in_(["running", "queued"]))
                ):
                    run.status = "failed"
                    run.error = "Worker interrupted by service restart; resume from Agent activity"
        self.scheduler.add_job(
            self.scheduled_search,
            "interval",
            seconds=30,
            next_run_time=utc_now() + timedelta(seconds=3),
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()

    def launch(self, options: dict[str, Any]) -> str:
        with self.lock:
            if cloud.enabled():
                with self.factory() as session:
                    busy = session.scalar(
                        select(PipelineRun).where(PipelineRun.status.in_(["queued", "running"]))
                    )
                    if busy:
                        raise ValueError("Wait for the active search before starting another")
            if self.active:
                raise ValueError("Wait for the active run before starting another")
            pipeline = Pipeline(self.settings)
            try:
                identity = pipeline.start(options)
            finally:
                pipeline.close()
            self.dispatch(identity)
            return identity

    def scheduled_search(self) -> None:
        if not self.settings.live_search_enabled or utc_now() < self.next_search_at:
            return
        with self.lock:
            if self.active:
                return
            status = readiness(self.settings)
            if not status["discovery_ready"]:
                self.scheduler_error = "Configure a job source in Settings"
                return
            stage = "all" if status["ai_pipeline_ready"] else "scout"
            try:
                self.last_scheduled_run = self.launch(
                    {
                        "demo": False,
                        "offline": stage == "scout" or self.settings.ai_provider == "local",
                        "dry_run": False,
                        "auto": self.settings.application_mode == "auto",
                        "stage": stage,
                        "trigger": "scheduled",
                        "source_names": [s["name"] for s in status["sources"] if s["ready"]],
                    }
                )
                self.scheduler_error = None
                self.next_search_at = utc_now() + timedelta(
                    minutes=self.settings.live_search_interval_minutes
                )
            except Exception:
                self.scheduler_error = "Search could not start; check Agent activity"
                self.next_search_at = utc_now() + timedelta(minutes=5)

    def live_status(self) -> dict[str, Any]:
        next_at = self.next_search_at.isoformat()
        if cloud.enabled():
            schedule_path = self.settings.data_dir / "cloud-schedule.json"
            if schedule_path.exists():
                next_at = json.loads(schedule_path.read_text()).get("next", next_at)
        return {
            **readiness(self.settings),
            "scheduler": {
                "enabled": self.settings.live_search_enabled,
                "running": cloud.enabled() or self.scheduler.running,
                "interval_minutes": self.settings.live_search_interval_minutes,
                "next_search_at": next_at if self.settings.live_search_enabled else None,
                "last_run_id": self.last_scheduled_run,
                "error": self.scheduler_error,
            },
        }

    def dispatch(self, identity: str, resume: dict[str, Any] | None = None) -> None:
        if cloud.enabled():
            cloud.active(self.settings.data_dir).enqueue(
                {"kind": "pipeline", "run_id": identity, "resume": resume}
            )
            return
        with self.lock:
            if identity in self.active:
                raise ValueError("Run already executing")
            self.active.add(identity)

        def worker() -> None:
            pipeline = Pipeline(self.settings.model_copy(deep=True))
            try:
                pipeline.execute(identity, resume)
                with self.factory() as session:
                    run = session.get(PipelineRun, identity)
                    should_apply = bool(
                        run
                        and run.status == "completed"
                        and run.options.get("auto")
                        and not run.options.get("dry_run")
                        and run.options.get("stage", "all") == "all"
                    )
                if self.settings.application_mode == "auto" and should_apply:
                    from lakshya.services.auto_apply import apply_ready

                    counts = apply_ready(self.settings)
                    with self.factory() as session, session.begin():
                        run = session.get(PipelineRun, identity)
                        if run:
                            run.result = {**(run.result or {}), "automatic_applications": counts}
            except Exception:
                # execute already persisted a redacted failure; poll/SSE delivers it.
                pass
            finally:
                pipeline.close()
                with self.lock:
                    self.active.discard(identity)

        self.executor.submit(worker)

    def close(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.executor.shutdown(wait=True)


def install_routes(
    router: APIRouter, settings: Settings, factory: sessionmaker[Session]
) -> RunManager:
    manager = RunManager(settings, factory)
    settings_lock = threading.Lock()

    def required(session: Session, kind: type[Any], identity: str) -> Any:
        row = session.get(kind, identity)
        if row is None:
            raise HTTPException(404, "Record not found")
        return row

    def application_json(session: Session, application: ApplicationRecord) -> dict[str, Any]:
        job = required(session, JobRecord, application.job_id)
        data = public_row(application)
        data["job"] = public_row(job)
        from lakshya.services.application_policy import application_policy

        data["auto_apply"] = application_policy(settings, application, job)
        last_event = session.scalar(
            select(StatusHistory)
            .where(StatusHistory.application_id == application.id)
            .order_by(StatusHistory.id.desc())
            .limit(1)
        )
        if (
            data["auto_apply"]["state"] != "finished"
            and last_event
            and last_event.note.startswith(
                ("auto_paused:", "browser_blocked:", "unknown_fields:", "Needs your help:")
            )
        ):
            data["auto_apply"]["eligible"] = False
            data["auto_apply"]["state"] = "needs_help"
            data["auto_apply"]["reasons"].insert(0, last_event.note)
            if last_event.note in {
                "Needs your help: needs-review",
                "auto_paused: Unknown, unsupported or missing fields require human input",
            }:
                questions = session.scalar(
                    select(StatusHistory)
                    .where(
                        StatusHistory.application_id == application.id,
                        StatusHistory.note.startswith("unknown_fields:"),
                    )
                    .order_by(StatusHistory.id.desc())
                    .limit(1)
                )
                if questions:
                    data["auto_apply"]["reasons"][0] = (
                        "Your answers are needed: "
                        + questions.note.removeprefix("unknown_fields:").strip()
                    )
        data["allowed_statuses"] = sorted(
            __import__("lakshya.services.lifecycle", fromlist=["TRANSITIONS"]).TRANSITIONS.get(
                application.status, set()
            )
            - {"approved", "applying", "applied"}
        )
        return data

    @router.get("/jobs")
    def jobs(
        q: str = "",
        source: str = "",
        remote_type: str = "",
        min_score: float = 0,
        demo: bool | None = None,
        freshness_hours: float | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if freshness_hours is not None and not 0 < freshness_hours <= 24:
            raise HTTPException(422, "Freshness must be between zero and 24 hours")
        query = select(JobRecord).order_by(
            JobRecord.match_score.desc(), JobRecord.created_at.desc()
        )
        if q:
            query = query.where(JobRecord.title.ilike(f"%{q}%") | JobRecord.company.ilike(f"%{q}%"))
        if source:
            query = query.where(JobRecord.source == source)
        if remote_type:
            query = query.where(JobRecord.remote_type == remote_type)
        if min_score:
            query = query.where(JobRecord.match_score >= min_score)
        if demo is not None:
            query = query.where(JobRecord.is_demo == demo)
        if freshness_hours is not None:
            query = query.where(
                JobRecord.posted_at >= utc_now() - timedelta(hours=freshness_hours),
                JobRecord.posted_at <= utc_now(),
            )
        with factory() as session:
            return [
                public_row(row)
                for row in session.scalars(query.limit(max(1, min(1000, limit))))
                if settings.environment != "production" or role_allowed(as_job(row), settings)
            ]

    @router.get("/jobs/{identity}")
    def job_detail(identity: str) -> dict[str, Any]:
        with factory() as session:
            row = required(session, JobRecord, identity)
            app = session.scalar(
                select(ApplicationRecord).where(ApplicationRecord.job_id == identity)
            )
            return {**public_row(row), "application_id": app.id if app else None}

    @router.get("/applications")
    def applications(
        status: str = "", q: str = "", demo: bool | None = None
    ) -> list[dict[str, Any]]:
        query = (
            select(ApplicationRecord)
            .join(JobRecord, ApplicationRecord.job_id == JobRecord.id)
            .order_by(ApplicationRecord.updated_at.desc())
        )
        if status:
            query = query.where(ApplicationRecord.status == status)
        if demo is not None:
            query = query.where(JobRecord.is_demo == demo)
        if q:
            query = query.where(JobRecord.title.ilike(f"%{q}%") | JobRecord.company.ilike(f"%{q}%"))
        with factory() as session:
            return [application_json(session, row) for row in session.scalars(query.limit(1000))]

    @router.get("/applications/{identity}")
    def application_detail(identity: str) -> dict[str, Any]:
        with factory() as session:
            row = required(session, ApplicationRecord, identity)
            result = application_json(session, row)
            result["timeline"] = [
                public_row(history)
                for history in session.scalars(
                    select(StatusHistory)
                    .where(StatusHistory.application_id == identity)
                    .order_by(StatusHistory.id)
                )
            ]
            profile_path = settings.data_dir / "profiles" / f"{row.profile_sha256}.json"
            result["master_resume"] = (
                MasterProfile.model_validate_json(profile_path.read_text()).raw_text
                if row.profile_sha256 and profile_path.exists()
                else "Import your resume to start."
            )
            if row.resume_path:
                files = application_files(row)
                result["tailored_resume"] = (
                    Path(files["text"]).read_text() if Path(files["text"]).exists() else ""
                )
                result["changes"] = (
                    Path(files["report"]).read_text() if Path(files["report"]).exists() else ""
                )
                result["cover_note"] = (
                    Path(files["cover_note"]).read_text()
                    if Path(files["cover_note"]).exists()
                    else ""
                )
            return result

    @router.patch("/applications/{identity}")
    def update_application(identity: str, body: StatusRequest) -> dict[str, Any]:
        with factory() as session, session.begin():
            row = required(session, ApplicationRecord, identity)
            if body.expected_status is not None and body.expected_status != row.status:
                raise HTTPException(409, "Status changed. Refresh and try again.")
            if body.status and body.status.value != row.status:
                if body.status in {
                    ApplicationStatus.APPROVED,
                    ApplicationStatus.APPLYING,
                    ApplicationStatus.APPLIED,
                }:
                    raise HTTPException(409, "Use the approval or submission confirmation action")
                try:
                    transition_status(session, row, body.status, source="user", note=body.note)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
            if body.notes is not None:
                row.notes = body.notes
            return application_json(session, row)

    @router.post("/applications/{identity}/approve")
    def approve(identity: str) -> dict[str, Any]:
        with factory() as session, session.begin():
            row = required(session, ApplicationRecord, identity)
            try:
                if artifact_hash(application_files(row)) != row.artifact_sha256:
                    raise ValueError("Bundle changed after critic review")
                job = required(session, JobRecord, row.job_id)
                master, _ = load_profile(settings, job.is_demo)
                if master.source_sha256 != row.profile_sha256:
                    raise ValueError("Master profile changed; regenerate the bundle")
                transition_status(session, row, "approved", source="user", human_approved=True)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            return application_json(session, row)

    @router.post("/applications/{identity}/reject")
    def reject(identity: str) -> dict[str, Any]:
        return update_application(
            identity, StatusRequest(status=ApplicationStatus.SKIPPED, note="Rejected at review")
        )

    @router.post("/applications/{identity}/confirm-manual")
    def confirm_manual(identity: str, body: dict[str, Any]) -> dict[str, Any]:
        if body != {"confirmed": True}:
            raise HTTPException(422, "Explicit confirmed=true is required")
        with factory() as session, session.begin():
            row = required(session, ApplicationRecord, identity)
            job = required(session, JobRecord, row.job_id)
            if job.is_demo:
                raise HTTPException(409, "Demo applications cannot be submitted")
            if row.status not in {"approved", "applying", "failed"}:
                raise HTTPException(409, "Only approved or uncertain submissions can be confirmed")
            if row.status == "failed" and row.submission_state != "uncertain":
                raise HTTPException(409, "Only uncertain failures can be confirmed manually")
            if row.status == "approved":
                transition_status(
                    session,
                    row,
                    "applying",
                    source="user",
                    note="User confirms external manual application",
                )
            if row.status == "failed" and row.submission_state == "uncertain":
                old = row.status
                row.status = "applied"
                row.applied_at = utc_now()
                session.add(
                    StatusHistory(
                        application_id=row.id,
                        old_status=old,
                        new_status="applied",
                        source="user",
                        note="User resolved uncertain submission as applied",
                    )
                )
            else:
                transition_status(
                    session,
                    row,
                    "applied",
                    source="user",
                    note="User confirmed successful external submission",
                )
            row.submission_state = "applied"
            row.follow_up_date = utc_now() + timedelta(days=settings.follow_up_days)
            return application_json(session, row)

    @router.post("/applications/{identity}/rerender")
    def rerender(identity: str) -> dict[str, Any]:
        with factory() as session, session.begin():
            row = required(session, ApplicationRecord, identity)
            job = required(session, JobRecord, row.job_id)
            if (
                row.status
                not in {
                    "shortlisted",
                    "resume_ready",
                    "needs_human_review",
                    "awaiting_approval",
                    "approved",
                }
                or row.submission_state
            ):
                raise HTTPException(409, "This application cannot be regenerated")
            if row.status == "approved":
                transition_status(
                    session,
                    row,
                    "awaiting_approval",
                    source="user",
                    note="Approval revoked for regeneration",
                )
            if row.status == "awaiting_approval":
                transition_status(session, row, "resume_ready", source="user")
            if row.status == "resume_ready":
                transition_status(session, row, "needs_human_review", source="user")
            row.critic_passed = False
            is_demo = job.is_demo
        return start_run(
            RunRequest(demo=is_demo, offline=is_demo, stage="tailor", job_ids=[job.id])
        )

    @router.get("/applications/{identity}/files/{kind}")
    def download(
        identity: str, kind: Literal["pdf", "docx", "report", "cover_note"]
    ) -> FileResponse:
        with factory() as session:
            row = required(session, ApplicationRecord, identity)
            try:
                path = Path(application_files(row)[kind]).resolve()
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
            if not path.is_relative_to(settings.output_dir.resolve()) or not path.is_file():
                raise HTTPException(404, "Artifact unavailable")
            return FileResponse(path, filename=path.name)

    @router.post("/applications/{identity}/followup")
    def followup(identity: str, body: dict[str, Any]) -> dict[str, Any]:
        with factory() as session, session.begin():
            row = required(session, ApplicationRecord, identity)
            draft_followups(session, settings)
            if "draft" in body:
                row.follow_up_draft = str(body["draft"])[:20000]
                row.follow_up_approved = False
            if body.get("approve") is True and row.follow_up_draft:
                row.follow_up_approved = True
            return application_json(session, row)

    @router.get("/stats")
    def stats() -> dict[str, Any]:
        with factory() as session:
            rows = list(session.scalars(select(ApplicationRecord)))
            jobs_count = session.scalar(select(func.count()).select_from(JobRecord)) or 0
            funnel = {
                status.value: sum(row.status == status.value for row in rows)
                for status in ApplicationStatus
            }
            responses = {"viewed", "interview_scheduled", "offer", "rejected"}
            applied = [r for r in rows if r.applied_at]
            response_delays = []
            for row in applied:
                assert row.applied_at is not None
                history = session.scalar(
                    select(StatusHistory)
                    .where(
                        StatusHistory.application_id == row.id,
                        StatusHistory.new_status.in_(responses),
                    )
                    .order_by(StatusHistory.changed_at)
                )
                if history:
                    response_delays.append(
                        (history.changed_at - row.applied_at).total_seconds() / 86400
                    )
            weekly = []
            for offset in range(6, -1, -1):
                day = (utc_now() - timedelta(days=offset)).date()
                weekly.append(
                    {
                        "day": day.isoformat(),
                        "applications": sum(
                            bool(r.applied_at and r.applied_at.date() == day) for r in rows
                        ),
                    }
                )
            return {
                "jobs": jobs_count,
                "applications": len(rows),
                "review_queue": funnel["awaiting_approval"] + funnel["needs_human_review"],
                "applied": len(applied),
                "response_rate": 100
                * sum(r.status in responses for r in applied)
                / max(1, len(applied)),
                "average_response_days": sum(response_delays) / len(response_delays)
                if response_delays
                else None,
                "funnel": funnel,
                "weekly": weekly,
                "due_followups": sum(
                    bool(
                        r.follow_up_date
                        and r.follow_up_date <= utc_now()
                        and r.status in {"applied", "viewed"}
                    )
                    for r in rows
                ),
            }

    @router.post("/jobs/{identity}/prepare", status_code=202)
    def prepare_job(identity: str) -> dict[str, str]:
        with factory() as session:
            job = required(session, JobRecord, identity)
            if job.is_demo:
                raise HTTPException(409, "Only real jobs can be prepared here")
            from lakshya.utils import is_fresh

            if not is_fresh(as_job(job), settings.freshness_hours):
                raise HTTPException(
                    409, "This job is outside your freshness window. Find a recent job first."
                )
        try:
            load_profile(settings)
            run_id = manager.launch(
                {
                    "stage": "all",
                    "job_ids": [identity],
                    "demo": False,
                    "offline": settings.ai_provider == "local",
                    "dry_run": False,
                    "auto": settings.application_mode == "auto",
                }
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"run_id": run_id, "message": "Preparing your resume for this job"}

    @router.get("/export")
    def export() -> FileResponse:
        with factory() as session:
            path = export_excel(session, settings.output_dir / "applications.xlsx")
        return FileResponse(path, filename="lakshya-applications.xlsx")

    @router.post("/runs", status_code=202)
    def start_run(body: RunRequest) -> dict[str, Any]:
        if body.demo and settings.environment == "production":
            raise HTTPException(422, "Demo runs are disabled in this live deployment")
        if body.auto and settings.application_mode != "auto":
            raise HTTPException(422, "Enable automatic applications in My preferences first")
        if not body.demo and body.stage != "scout":
            try:
                load_profile(settings)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if not body.offline and settings.ai_provider != "local":
                credential = (
                    settings.gemini_api_key
                    if settings.ai_provider == "gemini"
                    else settings.anthropic_api_key
                )
                if not credential.get_secret_value():
                    raise HTTPException(
                        409,
                        f"Configure {settings.ai_provider} credentials or choose local processing",
                    )
        options = body.model_dump() | {
            "offline": body.offline
            or body.demo
            or body.stage == "scout"
            or settings.ai_provider == "local"
        }
        if not body.demo:
            options["source_names"] = [
                s["name"] for s in readiness(settings)["sources"] if s["ready"]
            ]
        try:
            identity = manager.launch(options)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"id": identity, "status": "queued"}

    @router.get("/live")
    def live() -> dict[str, Any]:
        return manager.live_status()

    @router.get("/runs")
    def runs() -> list[dict[str, Any]]:
        with factory() as session:
            return [
                public_row(row)
                for row in session.scalars(
                    select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(100)
                )
            ]

    @router.get("/runs/{identity}")
    def run_detail(identity: str) -> dict[str, Any]:
        with factory() as session:
            row = required(session, PipelineRun, identity)
            return {
                **public_row(row),
                "agents": [
                    public_row(agent)
                    for agent in session.scalars(
                        select(AgentRun)
                        .where(AgentRun.run_id == identity)
                        .order_by(AgentRun.started_at)
                    )
                ],
            }

    @router.post("/runs/{identity}/{control}")
    def run_control(
        identity: str,
        control: Literal["pause", "resume", "stop"],
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with factory() as session, session.begin():
            run = required(session, PipelineRun, identity)
            if run.status in {"completed", "stopped"}:
                raise HTTPException(409, "Run already finished")
            if control == "resume":
                if run.status not in {"paused", "failed"}:
                    raise HTTPException(409, "Only paused or failed runs can be resumed")
                decisions = body or {}
                # Gather persisted user decisions; a resume payload cannot manufacture approval.
                ready = run.result.get("ready", [])
                decisions = {
                    app.id: "approve" if app.status == "approved" else "reject"
                    for app in session.scalars(
                        select(ApplicationRecord).where(ApplicationRecord.id.in_(ready))
                    )
                    if app.status in {"approved", "skipped"}
                }
                if ready and len(decisions) != len(ready):
                    raise HTTPException(409, "Review all bundles before resuming")
                run.requested_control = None
            elif control == "stop":
                run.requested_control = "stop"
                if run.status in {"paused", "failed", "queued"}:
                    run.status, run.finished_at = "stopped", utc_now()
            else:
                run.requested_control = "pause"
        if control == "resume":
            try:
                manager.dispatch(identity, decisions)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        return {"id": identity, "control": control}

    @router.get("/runs/{identity}/events")
    async def events(identity: str, request: Request, after: int = 0) -> StreamingResponse:
        with factory() as session:
            required(session, PipelineRun, identity)

        async def generate() -> AsyncIterator[str]:
            cursor = max(after, int(request.headers.get("Last-Event-ID", "0")))
            while not await request.is_disconnected():
                with factory() as session:
                    rows = list(
                        session.scalars(
                            select(AgentEvent)
                            .where(AgentEvent.run_id == identity, AgentEvent.id > cursor)
                            .order_by(AgentEvent.id)
                        )
                    )
                    run = session.get(PipelineRun, identity)
                    for row in rows:
                        cursor = row.id
                        yield f"id: {row.id}\nevent: agent\ndata: {json.dumps(public_row(row), default=str)}\n\n"
                    if run and run.status in {"completed", "failed", "paused", "stopped"}:
                        yield f"event: status\ndata: {json.dumps({'status': run.status})}\n\n"
                        break
                if cloud.enabled():
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/agents")
    def agents() -> list[dict[str, Any]]:
        with factory() as session:
            rows = list(session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc())))
            names = sorted(
                set(r.agent_name for r in rows)
                | {
                    "profile",
                    "scout",
                    "dedup",
                    "jd_analyst",
                    "matcher",
                    "tailor",
                    "critic",
                    "application",
                    "tracker",
                    "followup",
                }
            )
            return [
                {
                    "name": name,
                    "status": next((r.status for r in rows if r.agent_name == name), "idle"),
                    "input_tokens": sum(r.input_tokens for r in rows if r.agent_name == name),
                    "output_tokens": sum(r.output_tokens for r in rows if r.agent_name == name),
                    "cost_usd": sum(r.cost_usd for r in rows if r.agent_name == name),
                }
                for name in names
            ]

    @router.get("/settings")
    def get_settings() -> dict[str, Any]:
        safe_fields = {
            "max_run_tokens",
            "max_day_tokens",
            "max_run_cost_usd",
            "max_day_cost_usd",
            "max_agent_iterations",
            "follow_up_days",
            "boards",
            "public_search",
            "model_prices_per_million",
            "max_experience_years",
            "allow_remote_india",
            "allow_global_remote",
            "embedding_backend",
            "application_mode",
            "daily_application_cap",
            "max_applications_per_run",
            "live_search_enabled",
            "live_search_interval_minutes",
            "embedding_model",
            "llm_request_interval_seconds",
            "max_run_llm_calls",
            "max_day_llm_calls",
        }
        from lakshya.scrapers.boards import STARTER_BOARDS, employer_boards

        return {
            **settings.public_summary(),
            **settings.model_dump(mode="json", include=safe_fields),
            "boards": {
                **settings.boards,
                **{name: employer_boards(settings, name) for name in STARTER_BOARDS},
            },
            "profile": profile_status(settings),
        }

    @router.patch("/settings")
    def patch_settings(body: dict[str, Any]) -> dict[str, Any]:
        editable = {
            "application_mode",
            "daily_application_cap",
            "max_applications_per_run",
            "live_search_enabled",
            "live_search_interval_minutes",
            "ai_provider",
            "llm_free_tier",
            "llm_request_interval_seconds",
            "max_run_llm_calls",
            "max_day_llm_calls",
            "target_roles",
            "locations",
            "match_threshold",
            "enabled_sources",
            "agent_models",
            "boards",
            "public_search",
            "model_prices_per_million",
            "follow_up_days",
            "max_run_tokens",
            "max_day_tokens",
            "max_run_cost_usd",
            "max_day_cost_usd",
            "allow_remote_india",
            "allow_global_remote",
            "embedding_backend",
        }
        if not body or set(body) - editable:
            raise HTTPException(422, "Settings contains unsupported fields")
        try:
            validated = Settings.model_validate(
                settings.model_dump()
                | {
                    "api_key": settings.api_key,
                    "anthropic_api_key": settings.anthropic_api_key,
                    "gemini_api_key": settings.gemini_api_key,
                    "adzuna_app_id": settings.adzuna_app_id,
                    "adzuna_app_key": settings.adzuna_app_key,
                }
                | body
            )
        except ValueError as exc:
            raise HTTPException(422, "Settings failed validation") from exc
        with settings_lock, manager.lock:
            if manager.active:
                raise HTTPException(409, "Wait for the active run before changing settings")
            path = (
                settings.config_file or Path(os.getenv("LAKSHYA_CONFIG", "config.yaml")).resolve()
            )
            data = yaml.safe_load(path.read_text())
            data.update(validated.model_dump(mode="json", include=set(body)))
            temp = path.with_suffix(".yaml.tmp")
            temp.write_text(yaml.safe_dump(data, sort_keys=False))
            temp.replace(path)
            for name in body:
                setattr(settings, name, getattr(validated, name))
            if {"live_search_enabled", "live_search_interval_minutes"}.intersection(body):
                manager.next_search_at = utc_now() + timedelta(seconds=30)
                if cloud.enabled():
                    from lakshya.cloud.worker import schedule

                    schedule(settings)
        return get_settings()

    @router.post("/settings/credentials")
    def set_credential(body: CredentialRequest) -> dict[str, Any]:
        field, env = {
            "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
            "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
            "adzuna_app_id": ("adzuna_app_id", "ADZUNA_APP_ID"),
            "adzuna_app_key": ("adzuna_app_key", "ADZUNA_APP_KEY"),
        }[body.provider]
        # Docker stores private credentials on the persistent data volume. Local .env is untouched.
        path = settings.data_dir / "credentials.json"
        with settings_lock:
            values = json.loads(path.read_text()) if path.exists() else {}
            values[env] = body.value
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(values, stream)
            setattr(settings, field, SecretStr(body.value))
            if settings.config_file is None or "accounts" not in settings.config_file.parts:
                os.environ[env] = body.value
            manager.next_search_at = utc_now() + timedelta(seconds=30)
        return {"provider": body.provider, "configured": True}

    @router.post("/profile/import")
    async def upload_resume(file: UploadFile) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt", ".md"}:
            raise HTTPException(422, "Upload PDF, DOCX or text")
        maximum = (4 if cloud.enabled() else 10) * 1024 * 1024
        data = await file.read(maximum + 1)
        if len(data) > maximum:
            raise HTTPException(413, "Resume exceeds the upload size limit")
        with manager.lock:
            if manager.active:
                raise HTTPException(409, "Wait for the active run before changing the resume")
        path = settings.data_dir / f"uploaded_resume{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            master = await asyncio.to_thread(import_profile, path, settings)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"imported": True, "facts": len(master.facts), "skills": master.skills}

    @router.get("/screening-answers")
    def answers() -> list[dict[str, Any]]:
        with factory() as session:
            return [public_row(row) for row in session.scalars(select(ScreeningAnswer))]

    @router.put("/screening-answers")
    def set_answer(body: AnswerRequest) -> dict[str, Any]:
        with factory() as session, session.begin():
            row = session.scalar(
                select(ScreeningAnswer).where(ScreeningAnswer.question == body.question)
            )
            if row is None:
                row = ScreeningAnswer(question=body.question, answer=body.answer)
                session.add(row)
            row.answer = body.answer
            session.flush()
            return public_row(row)

    @router.post("/gmail/suggestions")
    def gmail_suggestions() -> list[dict[str, Any]]:
        from lakshya.services.gmail import suggest_statuses

        if settings.config_file and "accounts" in settings.config_file.parts:
            raise HTTPException(409, "Email integration is not connected to this account")
        try:
            with factory() as session:
                return suggest_statuses(session)
        except Exception as exc:
            raise HTTPException(
                409, "Gmail read-only access unavailable. Check the token, scope and expiry."
            ) from exc

    return manager
