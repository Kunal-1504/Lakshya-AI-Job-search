"""Durable LangGraph orchestration with independent source failures and human interrupts."""

import asyncio
import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from lakshya.agents.critic import review_bundle
from lakshya.config import Settings
from lakshya.db.base import utc_now
from lakshya.db.models import AgentRun, ApplicationRecord, JobRecord, PipelineRun
from lakshya.db.seed import seed_demo
from lakshya.db.session import build_engine
from lakshya.deduplication import deduplicate, same_job
from lakshya.llm import LLM, ProviderUnavailable
from lakshya.logging import redact
from lakshya.matcher import Matcher, location_allowed, required_years, role_allowed
from lakshya.models import Job
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.resume_tailor import ResumeTailor
from lakshya.services.exports import draft_followups
from lakshya.services.lifecycle import transition_status
from lakshya.services.profile import load_profile
from lakshya.services.store import application_files, as_job, event, save_job
from lakshya.utils import is_fresh


class State(TypedDict, total=False):
    run_id: str
    jobs: list[dict[str, Any]]
    applications: list[str]
    ready: list[str]
    round: int
    options: dict[str, Any]
    decisions: dict[str, str]
    errors: list[str]


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_failure: str | None = None
        self.engine = build_engine(settings)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            settings.data_dir / "checkpoints.sqlite3", check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self.connection)
        builder = StateGraph(State)
        for name in (
            "profile",
            "scout",
            "dedup",
            "match",
            "tailor",
            "critic",
            "approval",
            "application",
            "tracker",
            "followup",
        ):
            builder.add_node(name, getattr(self, name))
        builder.add_edge(START, "profile")
        for before, after in (
            ("profile", "scout"),
            ("scout", "dedup"),
            ("dedup", "match"),
            ("match", "tailor"),
            ("tailor", "critic"),
            ("approval", "application"),
            ("application", "tracker"),
            ("tracker", "followup"),
            ("followup", END),
        ):
            builder.add_edge(before, after)
        builder.add_conditional_edges(
            "critic", self.critic_route, {"retry": "tailor", "done": "approval"}
        )
        self.graph = builder.compile(checkpointer=self.checkpointer)

    def close(self) -> None:
        self.connection.close()
        self.engine.dispose()

    def start(self, options: dict[str, Any]) -> str:
        if self.settings.environment == "production" and options.get("demo"):
            raise ValueError("Demo runs are disabled in the live deployment")
        identity = str(uuid4())
        with Session(self.engine) as session, session.begin():
            session.add(
                PipelineRun(
                    id=identity,
                    graph_thread_id=identity,
                    dry_run=bool(options.get("dry_run", True)),
                    auto=bool(options.get("auto", False)),
                    options=options,
                    trigger=options.get("trigger", "manual"),
                )
            )
        return identity

    def execute(
        self, identity: str, resume: dict[str, Any] | None = None, *, one_step: bool = False
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            run = session.get(PipelineRun, identity)
            if not run:
                raise ValueError("Run not found")
            if run.status in {"completed", "stopped"}:
                raise ValueError("Run has already finished")
            run.status, run.error = "running", None
            options = run.options.copy()
            if resume is not None or not one_step:
                run.requested_control = None
        configuration: RunnableConfig = {
            "configurable": {"thread_id": identity},
            "recursion_limit": 100,
        }
        snapshot = self.graph.get_state(configuration)
        graph_input: Any = (
            Command(resume=resume or {})
            if snapshot.tasks and any(t.interrupts for t in snapshot.tasks)
            else (
                None
                if snapshot.next
                else {
                    "run_id": identity,
                    "options": options,
                    "round": 0,
                    "jobs": [],
                    "applications": [],
                    "ready": [],
                    "errors": [],
                }
            )
        )
        try:
            result = self.graph.invoke(
                graph_input, configuration, interrupt_after="*" if one_step else None
            )
            more = bool(self.graph.get_state(configuration).next) if one_step else False
            interrupted = result.get("__interrupt__", ())
            with Session(self.engine) as session, session.begin():
                run = session.get(PipelineRun, identity)
                assert run is not None
                run.status = "paused" if interrupted else ("queued" if more else "completed")
                run.result = {k: v for k, v in result.items() if k != "__interrupt__"}
                if interrupted:
                    run.result["interrupts"] = [item.value for item in interrupted]
                elif not more:
                    run.finished_at = utc_now()
                event(session, identity, "orchestrator", run.status, {"status": run.status})
            return result
        except Exception as exc:
            with Session(self.engine) as session, session.begin():
                run = session.get(PipelineRun, identity)
                assert run is not None
                run.status, run.error = (
                    ("stopped" if run.requested_control == "stop" else "failed"),
                    redact(str(exc)),
                )
                event(session, identity, "orchestrator", "Run failed", {"error": run.error})
            raise

    def control(self, state: State) -> None:
        with Session(self.engine) as session:
            run = session.get(PipelineRun, state["run_id"])
            assert run is not None
            requested = run.requested_control
        if requested == "stop":
            raise ValueError("Run stopped by user")
        if requested == "pause":
            interrupt({"kind": "control", "message": "Run paused at a safe stage boundary"})

    def agent(
        self,
        state: State,
        name: str,
        operation: Callable[[LLM | None], dict[str, Any]],
        use_llm: bool = False,
    ) -> dict[str, Any]:
        self.control(state)
        started = time.perf_counter()
        with Session(self.engine) as session, session.begin():
            row = AgentRun(
                run_id=state["run_id"],
                agent_name=name,
                iteration=max(1, state.get("round", 1)),
                input_summary={
                    "job_count": len(state.get("jobs", [])),
                    "options": state["options"],
                },
            )
            session.add(row)
            session.flush()
            agent_id = row.id
            event(session, state["run_id"], name, "Started", agent_run_id=agent_id, tool_name=name)
        try:
            if use_llm and self.model_failure:
                raise ProviderUnavailable(self.model_failure)
            llm = (
                LLM(self.settings, self.engine, state["run_id"], agent_id, name)
                if use_llm
                and not state["options"].get("offline")
                and self.settings.ai_provider != "local"
                else None
            )
            output = operation(llm)
            status, error = "completed", None
        except Exception as exc:
            if isinstance(exc, ProviderUnavailable):
                self.model_failure = str(exc)
            status, error, output = "failed", redact(str(exc)), {}
        with Session(self.engine) as session, session.begin():
            completed_row = session.get(AgentRun, agent_id)
            assert completed_row is not None
            completed_row.status, completed_row.error, completed_row.output_summary = (
                status,
                error,
                output,
            )
            completed_row.finished_at, completed_row.duration_ms = (
                utc_now(),
                (time.perf_counter() - started) * 1000,
            )
            event(
                session,
                state["run_id"],
                name,
                status,
                {"output": output, "error": error},
                agent_id,
                name,
            )
        if error:
            raise ValueError(f"{name}: {error}")
        return output

    def profile(self, state: State) -> dict[str, Any]:
        if state["options"].get("stage") == "scout" and not state["options"].get("demo"):
            self.agent(state, "profile", lambda _: {"mode": "discovery_without_personal_resume"})
            return {}
        master, _ = load_profile(self.settings, state["options"].get("demo", False))
        self.agent(
            state,
            "profile",
            lambda _: {"profile_sha256": master.source_sha256, "evidence_facts": len(master.facts)},
        )
        return {}

    def scout(self, state: State) -> dict[str, Any]:
        if state["options"].get("job_ids"):
            with Session(self.engine) as session:
                return {
                    "jobs": [
                        as_job(j).model_dump(mode="json")
                        for j in session.scalars(
                            select(JobRecord).where(JobRecord.id.in_(state["options"]["job_ids"]))
                        )
                    ]
                }
        if state["options"].get("stage") in {"match", "tailor"}:
            with Session(self.engine) as session:
                jobs = [
                    as_job(j).model_dump(mode="json")
                    for j in session.scalars(
                        select(JobRecord).where(
                            JobRecord.is_demo == bool(state["options"].get("demo"))
                        )
                    )
                ]
            return {"jobs": jobs}
        if state["options"].get("demo"):

            def demo(_: LLM | None) -> dict[str, Any]:
                with Session(self.engine) as session, session.begin():
                    seed_demo(session)
                    rows = list(
                        session.scalars(select(JobRecord).where(JobRecord.is_demo.is_(True)))
                    )
                    for row in rows:
                        row.posted_at = utc_now()
                        row.description = "Graduate role: Python SQL Pandas NumPy scikit-learn Git Excel Machine Learning. 0-1 years experience. Academic projects welcome. Pune or remote India."
                    return {"jobs": [as_job(j).model_dump(mode="json") for j in rows]}

            return self.agent(state, "scout:demo", demo)
        return asyncio.run(self.collect(state))

    async def collect(self, state: State) -> dict[str, Any]:
        from lakshya.scrapers.base import HTTP
        from lakshya.scrapers.registry import REGISTRY

        def trace(payload: dict[str, Any]) -> None:
            with Session(self.engine) as session, session.begin():
                event(
                    session,
                    state["run_id"],
                    "scout:http",
                    str(payload["event"]),
                    payload,
                    tool_name="http.get",
                )

        http = HTTP(self.settings, trace=trace)

        async def one(name: str) -> list[dict[str, Any]]:
            self.control(state)
            started = time.perf_counter()
            with Session(self.engine) as session, session.begin():
                row = AgentRun(run_id=state["run_id"], agent_name=f"scout:{name}")
                session.add(row)
                session.flush()
                agent_id = row.id
                event(
                    session,
                    state["run_id"],
                    f"scout:{name}",
                    "Started",
                    agent_run_id=agent_id,
                    tool_name="http.get",
                )
            try:
                if name not in REGISTRY:
                    raise ValueError("Unknown source")
                cache_key = hashlib.sha256(
                    json.dumps(
                        {
                            "collector_version": 4,
                            "source": name,
                            "roles": self.settings.target_roles,
                            "locations": self.settings.locations,
                            "boards": self.settings.boards,
                            "public_search": self.settings.public_search,
                            "max_pages": self.settings.max_pages,
                            "limit": self.settings.max_jobs_per_source,
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                cache = self.settings.data_dir / "source-cache" / f"{cache_key}.json"
                ttl = {"remotive": 21600, "himalayas": 86400}.get(name, 1800)
                if cache.exists() and time.time() - cache.stat().st_mtime < ttl:
                    output = [
                        Job.model_validate(item).model_dump(mode="json")
                        for item in json.loads(cache.read_text())
                    ]
                    origin = "cached_public_feed"
                else:
                    jobs = await REGISTRY[name](self.settings, http).collect()
                    output = [j.model_dump(mode="json") for j in jobs]
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache.with_suffix(".tmp")
                    temporary.write_text(json.dumps(output))
                    temporary.replace(cache)
                    origin = "live_http"
                status, error = "completed", None
            except Exception as exc:
                output, status, error = [], "failed", redact(str(exc))
                origin = "failed"
            with Session(self.engine) as session, session.begin():
                completed_row = session.get(AgentRun, agent_id)
                assert completed_row is not None
                completed_row.status, completed_row.error, completed_row.output_summary = (
                    status,
                    error,
                    {"jobs": len(output), "origin": origin},
                )
                completed_row.finished_at, completed_row.duration_ms = (
                    utc_now(),
                    (time.perf_counter() - started) * 1000,
                )
                event(
                    session,
                    state["run_id"],
                    f"scout:{name}",
                    status,
                    {"jobs": len(output), "error": error, "origin": origin},
                    agent_id,
                    "http.get",
                )
            return output

        try:
            results = await asyncio.gather(
                *(
                    one(name)
                    for name in state["options"].get("source_names", self.settings.enabled_sources)
                )
            )
        finally:
            await http.close()
        return {"jobs": [job for rows in results for job in rows]}

    def dedup(self, state: State) -> dict[str, Any]:
        def work(_: LLM | None) -> dict[str, Any]:
            jobs = deduplicate([Job.model_validate(j) for j in state["jobs"]])
            retained = []
            with Session(self.engine) as session:
                excluded = [
                    as_job(job)
                    for job, app in session.execute(
                        select(JobRecord, ApplicationRecord).join(
                            ApplicationRecord, ApplicationRecord.job_id == JobRecord.id
                        )
                    ).all()
                    if app.status
                    in {
                        "applied",
                        "skipped",
                        "viewed",
                        "offer",
                        "rejected",
                        "interview_scheduled",
                        "withdrawn",
                    }
                    or app.submission_state
                    or (
                        state["options"].get("stage") != "scout"
                        and app.status
                        in {"approved", "awaiting_approval", "resume_ready", "applying"}
                    )
                ]
            for job in jobs:
                years = required_years(job.description)
                if not state["options"].get("demo") and (
                    not role_allowed(job, self.settings)
                    or not location_allowed(job, self.settings)
                    or (years is not None and years > self.settings.max_experience_years)
                    or re.search(
                        r"\b(senior|sr\.?|lead|staff|principal|manager|director|head)\b",
                        job.title,
                        re.I,
                    )
                ):
                    continue
                if (
                    state["options"].get("stage") == "scout"
                    or is_fresh(job, self.settings.freshness_hours)
                ) and not any(
                    same_job(job, old) or str(job.apply_url) == str(old.apply_url)
                    for old in excluded
                ):
                    retained.append(job.model_dump(mode="json"))
            return {"jobs": retained}

        return self.agent(state, "dedup", work)

    def match(self, state: State) -> dict[str, Any]:
        if state["options"].get("stage") == "scout":
            with Session(self.engine) as session, session.begin():
                for data in state["jobs"]:
                    save_job(session, Job.model_validate(data), state["options"].get("demo", False))
            return {"applications": []}
        _, profile = load_profile(self.settings, state["options"].get("demo", False))
        applications = []
        with Session(self.engine) as session, session.begin():
            for data in state["jobs"]:
                save_job(session, Job.model_validate(data), state["options"].get("demo", False))
        for data in state["jobs"]:
            job = Job.model_validate(data)

            try:
                # JD and matcher get separate model routing and measured traces.
                def analyze_job(llm: LLM | None, job: Job = job) -> dict[str, Any]:
                    return Matcher(self.settings, llm).analyze(profile, job).model_dump(mode="json")

                analysis = self.agent(state, "jd_analyst", analyze_job, True)

                def work(
                    llm: LLM | None, job: Job = job, analysis_data: dict[str, Any] = analysis
                ) -> dict[str, Any]:
                    settings = (
                        self.settings.model_copy(update={"embedding_backend": "lexical"})
                        if state["options"].get("demo")
                        else self.settings
                    )
                    matcher = Matcher(settings, llm)
                    from lakshya.models import JDAnalysis

                    return matcher.match(
                        profile,
                        job,
                        JDAnalysis.model_validate(analysis_data) if llm is None else None,
                    ).model_dump(mode="json")

                result = self.agent(state, "matcher", work, True)
            except Exception as exc:
                with Session(self.engine) as session, session.begin():
                    event(
                        session,
                        state["run_id"],
                        "matcher",
                        "Job isolated after failure",
                        {"job": job.id, "error": redact(str(exc))},
                    )
                continue
            with Session(self.engine) as session, session.begin():
                row, app = save_job(session, job, state["options"].get("demo", False))
                row.match_score, row.jd_analysis = result["score"], result["analysis"]
                row.missing_skills = result["analysis"]["missing_skills"]
                row.matched_skills = [
                    s for s in profile.skills if s in result["analysis"]["required_skills"]
                ]
                row.match_reasoning = (
                    "; ".join(result["reasons"])
                    or f"Semantic {result['semantic_score']}; skills {result['skill_score']}; title {result['role_score']}"
                )
                if result["shortlisted"]:
                    if app.status == "new":
                        transition_status(session, app, "shortlisted", note=row.match_reasoning)
                    if app.status in {"shortlisted", "needs_human_review", "failed"}:
                        applications.append(app.id)
        # Match all retained jobs before bounding expensive document rendering. A weak
        # first feed row must not hide a later eligible direct-employer application.
        with Session(self.engine) as session:
            candidates = list(
                session.execute(
                    select(ApplicationRecord, JobRecord)
                    .join(JobRecord, ApplicationRecord.job_id == JobRecord.id)
                    .where(ApplicationRecord.id.in_(applications))
                )
            )
            from lakshya.applier import provider

            candidates.sort(
                key=lambda pair: (
                    bool(state["options"].get("auto"))
                    and (pair[1].match_score or 0) >= 80
                    and provider(pair[1].apply_url) in AUTO_PLATFORMS,
                    pair[1].match_score or 0,
                    pair[0].id,
                ),
                reverse=True,
            )
            limit = self.settings.max_applications_per_run
            if __import__("os").getenv("LAKSHYA_CLOUD") == "1":
                limit = min(limit, 2)
            return {"applications": [app.id for app, _ in candidates[:limit]]}

    def tailor(self, state: State) -> dict[str, Any]:
        if state["options"].get("stage") in {"scout", "match"}:
            return {"round": 1}
        master, profile = load_profile(self.settings, state["options"].get("demo", False))
        for identity in state.get("applications", []):
            with Session(self.engine) as session:
                app = session.get(ApplicationRecord, identity)
                assert app is not None
                if app.critic_passed and app.status == "awaiting_approval":
                    continue
                row = session.get(JobRecord, app.job_id)
                assert row is not None
                job = as_job(row)
                feedback = app.critic_report
            try:

                def tailor_job(
                    llm: LLM | None, job: Job = job, feedback: dict[str, Any] = feedback
                ) -> dict[str, Any]:
                    return ResumeTailor(self.settings, llm).tailor(profile, job, feedback)

                files = self.agent(state, "tailor", tailor_job, True)
                with Session(self.engine) as session, session.begin():
                    app = session.get(ApplicationRecord, identity)
                    assert app is not None
                    app.resume_path, app.docx_path = files["pdf"], files["docx"]
                    app.cover_note_path, app.changes_report_path = (
                        files["cover_note"],
                        files["report"],
                    )
                    app.profile_sha256, app.critic_passed = master.source_sha256, False
                    app.approved_artifact_sha256, app.approved_at = None, None
                    if app.status != "resume_ready":
                        transition_status(
                            session, app, "resume_ready", note="Evidence-only artifacts generated"
                        )
            except Exception as exc:
                with Session(self.engine) as session, session.begin():
                    app = session.get(ApplicationRecord, identity)
                    assert app is not None
                    app.critic_passed = False
                    app.status = "needs_human_review"
                    event(
                        session,
                        state["run_id"],
                        "tailor",
                        "Job isolated after failure",
                        {"application_id": identity, "error": redact(str(exc))},
                    )
        return {"round": state.get("round", 0) + 1}

    def critic(self, state: State) -> dict[str, Any]:
        if state["options"].get("stage") in {"scout", "match"}:
            return {"ready": []}
        _, profile = load_profile(self.settings, state["options"].get("demo", False))
        ready = []
        for identity in state.get("applications", []):
            with Session(self.engine) as session:
                app = session.get(ApplicationRecord, identity)
                assert app is not None
                if not app.resume_path:
                    continue
                row = session.get(JobRecord, app.job_id)
                assert row is not None
                job, files = as_job(row), application_files(app)

            def critique_job(
                llm: LLM | None, job: Job = job, files: dict[str, str] = files
            ) -> dict[str, Any]:
                return review_bundle(profile, job, files, llm).model_dump(mode="json")

            try:
                report = self.agent(state, "critic", critique_job, True)
            except Exception as exc:
                from lakshya.services.store import artifact_hash

                try:
                    digest = artifact_hash(files)
                except OSError:
                    digest = ""
                report = {
                    "passed": False,
                    "score": 0,
                    "unsupported_claims": [],
                    "missing_keywords": [],
                    "formatting_issues": [redact(str(exc))],
                    "typos": [],
                    "artifact_sha256": digest,
                }
            with Session(self.engine) as session, session.begin():
                app = session.get(ApplicationRecord, identity)
                assert app is not None
                app.critic_report, app.critic_passed = report, report["passed"]
                app.artifact_sha256 = report["artifact_sha256"]
                if report["passed"]:
                    if app.status != "awaiting_approval":
                        transition_status(
                            session, app, "awaiting_approval", note="Independent critic passed"
                        )
                    ready.append(identity)
                elif state["round"] >= self.settings.max_agent_iterations:
                    transition_status(
                        session,
                        app,
                        "needs_human_review",
                        note="Critic rejected after maximum retries",
                    )
        return {"ready": ready}

    def critic_route(self, state: State) -> str:
        return (
            "retry"
            if len(state.get("ready", [])) < len(state.get("applications", []))
            and state["round"] < self.settings.max_agent_iterations
            else "done"
        )

    def approval(self, state: State) -> dict[str, Any]:
        self.control(state)
        if not state.get("ready") or state["options"].get("dry_run", True):
            return {"decisions": {}}
        if state["options"].get("auto"):
            from lakshya.applier import provider

            decisions = {}
            with Session(self.engine) as session:
                for identity in state["ready"][: min(10, self.settings.max_applications_per_run)]:
                    app = session.get(ApplicationRecord, identity)
                    assert app is not None
                    job = session.get(JobRecord, app.job_id)
                    assert job is not None
                    if (
                        not job.is_demo
                        and (job.match_score or 0) >= 80
                        and provider(job.apply_url) in AUTO_PLATFORMS
                    ):
                        decisions[identity] = "approve"
            return {"decisions": decisions}
        decisions = interrupt(
            {
                "kind": "approval",
                "application_ids": state["ready"],
                "message": "Review each artifact bundle. Approval prepares it for the local application assistant.",
            }
        )
        return {"decisions": decisions}

    def application(self, state: State) -> dict[str, Any]:
        self.agent(
            state,
            "application",
            lambda _: {
                "dry_run": state["options"].get("dry_run", True),
                "reviewed_bundles": len(state.get("ready", [])),
                "submission": "disabled"
                if state["options"].get("dry_run", True)
                else "local_browser_assistant",
            },
        )
        return {}

    def tracker(self, state: State) -> dict[str, Any]:
        def work(_: LLM | None) -> dict[str, Any]:
            with Session(self.engine) as session, session.begin():
                for identity, decision in state.get("decisions", {}).items():
                    if identity not in state.get("ready", []):
                        continue
                    app = session.get(ApplicationRecord, identity)
                    assert app is not None
                    if app.status == "awaiting_approval" and decision in {"approve", "reject"}:
                        transition_status(
                            session,
                            app,
                            "approved" if decision == "approve" else "skipped",
                            source="user",
                            human_approved=decision == "approve",
                        )
                return {"tracked": len(state.get("ready", []))}

        self.agent(state, "tracker", work)
        return {}

    def followup(self, state: State) -> dict[str, Any]:
        def work(_: LLM | None) -> dict[str, Any]:
            with Session(self.engine) as session, session.begin():
                return {"drafts_created": draft_followups(session, self.settings)}

        self.agent(state, "followup", work)
        return {}
