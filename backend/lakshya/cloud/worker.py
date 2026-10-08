"""One bounded pipeline stage per durable queue delivery; delayed ticks schedule searches."""

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from lakshya.cloud import store
from lakshya.db.base import utc_now
from lakshya.db.models import PipelineRun
from lakshya.pipeline import Pipeline
from lakshya.services.readiness import readiness


def schedule(settings: Any) -> None:
    path = settings.data_dir / "cloud-schedule.json"
    generation = str(uuid4())
    path.write_text(
        json.dumps(
            {"generation": generation, "next": (utc_now() + timedelta(seconds=30)).isoformat()}
        )
    )
    if settings.live_search_enabled:
        store.active(settings.data_dir).enqueue({"kind": "tick", "generation": generation}, 30)


def process(accounts: Any, identity: str) -> dict[str, bool]:
    with store.connection() as db:
        row = db.execute("SELECT * FROM cloud_commands WHERE id=%s", (identity,)).fetchone()
    if not row or row["done"]:
        return {"done": True}
    user = row["user_id"]
    directory = accounts.settings.data_dir / "accounts" / user
    with store.workspace(user, directory) as workspace:
        # Recheck after locking: a redelivery may have waited behind its original delivery.
        row = workspace.db.execute(
            "SELECT * FROM cloud_commands WHERE id=%s", (identity,)
        ).fetchone()
        if not row or row["done"]:
            return {"done": True}
        app = accounts.workspace(user)
        manager = app.state.run_manager
        settings = app.state.settings
        payload = row["payload"]
        try:
            if payload["kind"] == "tick":
                path = directory / "cloud-schedule.json"
                current = json.loads(path.read_text()) if path.exists() else {}
                if (
                    settings.live_search_enabled
                    and current.get("generation") == payload["generation"]
                ):
                    with manager.factory() as session:
                        busy = session.scalar(
                            select(PipelineRun).where(PipelineRun.status.in_(["queued", "running"]))
                        )
                    status = readiness(settings)
                    if not busy and status["discovery_ready"]:
                        stage = "all" if status["ai_pipeline_ready"] else "scout"
                        manager.launch(
                            {
                                "demo": False,
                                "offline": settings.ai_provider == "local" or stage == "scout",
                                "auto": settings.application_mode == "auto",
                                "dry_run": False,
                                "stage": stage,
                                "trigger": "scheduled",
                                "source_names": [
                                    s["name"] for s in status["sources"] if s["ready"]
                                ],
                            }
                        )
                    delay = settings.live_search_interval_minutes * 60
                    current["next"] = (utc_now() + timedelta(seconds=delay)).isoformat()
                    path.write_text(json.dumps(current))
                    workspace.enqueue(payload, delay)
            elif payload["kind"] == "pipeline":
                run_id = payload["run_id"]
                with manager.factory() as session:
                    run = session.get(PipelineRun, run_id)
                    terminal = not run or run.status in {"completed", "stopped", "failed", "paused"}
                if not terminal or payload.get("resume") is not None:
                    pipeline = Pipeline(settings)
                    try:
                        pipeline.execute(run_id, payload.get("resume"), one_step=True)
                    except Exception:
                        # Pipeline records a readable failure. Explicit resume is required.
                        pass
                    finally:
                        pipeline.close()
                    with manager.factory() as session:
                        run = session.get(PipelineRun, run_id)
                        if run and run.status == "queued":
                            workspace.enqueue({"kind": "pipeline", "run_id": run_id})
                        elif (
                            run
                            and run.status == "completed"
                            and run.options.get("auto")
                            and not run.options.get("dry_run")
                            and run.options.get("stage", "all") == "all"
                        ):
                            for application_id in run.result.get("ready", [])[
                                : settings.max_applications_per_run
                            ]:
                                workspace.enqueue(
                                    {
                                        "kind": "apply",
                                        "run_id": run_id,
                                        "application_id": application_id,
                                    }
                                )
            elif payload["kind"] == "apply":
                from lakshya.services.auto_apply import apply_ready

                if settings.application_mode == "auto":
                    counts = apply_ready(settings, [payload["application_id"]])
                    with manager.factory() as session, session.begin():
                        run = session.get(PipelineRun, payload["run_id"])
                        if run:
                            previous = run.result.get("automatic_applications", {})
                            run.result = {
                                **run.result,
                                "automatic_applications": {
                                    name: previous.get(name, 0) + count
                                    for name, count in counts.items()
                                },
                            }
            else:
                raise ValueError("Unknown cloud command")
        finally:
            manager.close()
            app.state.engine.dispose()
            accounts.apps.pop(user, None)
        # Snapshot + follow-up messages are committed before acknowledging the delivery.
        workspace.save()
        workspace.db.execute("UPDATE cloud_commands SET done=TRUE WHERE id=%s", (identity,))
        workspace.db.commit()
    return {"done": True}
