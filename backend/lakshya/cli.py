from pathlib import Path
from typing import Annotated

import structlog
import typer
from alembic.runtime.migration import MigrationContext
from rich.console import Console

from lakshya.config import Settings, load_settings
from lakshya.db.migrate import upgrade_database
from lakshya.db.seed import seed_demo
from lakshya.db.session import build_engine, session_factory
from lakshya.logging import configure_logging, redact

app = typer.Typer(
    no_args_is_help=True, help="Lakshya — discover, tailor, review and track applications"
)
console = Console()


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", help="Path to config.yaml")] = None,
) -> None:
    console.print("  /\\  Lakshya\n /__\\ aim · prepare · approve", markup=False)
    try:
        settings = load_settings(config)
        configure_logging(settings.log_file)
        ctx.obj = settings
    except Exception as exc:
        console.print(f"Configuration error: {redact(str(exc))}", markup=False)
        raise typer.Exit(1) from exc


def current_settings(ctx: typer.Context) -> Settings:
    settings: Settings = ctx.obj
    return settings


@app.command("init-db")
def init_db(
    ctx: typer.Context,
    seed: Annotated[
        bool, typer.Option("--seed-demo", help="Add three clearly fictional demo jobs")
    ] = False,
) -> None:
    """Apply versioned Alembic migrations; optionally seed an isolated local demonstration."""
    settings = current_settings(ctx)
    upgrade_database(settings)
    if seed:
        engine = build_engine(settings)
        factory = session_factory(engine)
        with factory() as session, session.begin():
            added = seed_demo(session)
        engine.dispose()
        console.print(f"Inserted {added} fictional demo jobs.")
    structlog.get_logger().info("database_initialized", demo_seed=seed)
    console.print("Database migrated to head.")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check database migration and credentials without displaying secrets."""
    settings = current_settings(ctx)
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    console.print({"phase": 1, "schema_revision": revision, **settings.public_summary()})
    if not revision:
        console.print("Database not initialized: run lakshya init-db.")
    if not settings.api_key.get_secret_value():
        console.print("Set LAKSHYA_API_KEY in your environment before running serve.")


@app.command()
def serve(
    ctx: typer.Context,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Start the dashboard API and pipeline worker."""
    import uvicorn

    from lakshya.api.app import create_app

    uvicorn.run(create_app(current_settings(ctx)), host=host, port=port, log_config=None)


@app.command("import-resume")
def import_resume(ctx: typer.Context, path: Path) -> None:
    """Import your PDF, DOCX or text resume into immutable master evidence."""
    from lakshya.services.profile import import_profile

    result = import_profile(path, current_settings(ctx))
    console.print(f"Imported {len(result.facts)} evidence facts; {len(result.skills)} skills.")


def run_pipeline(
    ctx: typer.Context, stage: str, dry_run: bool, demo: bool, offline: bool, auto: bool = False
) -> None:
    from lakshya.pipeline import Pipeline

    settings = current_settings(ctx)
    upgrade_database(settings)
    if stage != "scout" and not demo and not (settings.data_dir / "master_profile.json").exists():
        raise typer.BadParameter("Import your actual resume first, or use scout for real discovery")
    pipeline = Pipeline(settings)
    try:
        identity = pipeline.start(
            {
                "stage": stage,
                "dry_run": dry_run,
                "demo": demo,
                "offline": offline or demo,
                "auto": auto,
            }
        )
        console.print(f"Run {identity}")
        result = pipeline.execute(identity)
        console.print(f"Prepared {len(result.get('ready', []))} reviewed bundles.")
        if auto and not dry_run:
            import asyncio

            from lakshya.applier import Applier
            from lakshya.services.profile import load_profile
            from lakshya.tracker import Tracker

            tracker = Tracker(settings)
            try:
                master, profile = load_profile(settings, demo)
                count = 0
                for identity in result.get("ready", []):
                    if count >= min(10, settings.max_applications_per_run):
                        break
                    record = tracker.get(identity)
                    try:
                        tracker.verify_approval(record, master.source_sha256)
                        console.print(
                            asyncio.run(
                                Applier(settings, tracker).apply(
                                    record, profile, master.source_sha256, auto=True
                                )
                            )
                        )
                        count += 1
                    except ValueError as exc:
                        console.print(redact(str(exc)))
            finally:
                tracker.close()
        if result.get("__interrupt__"):
            console.print("Run paused for approval. Review the applications in the dashboard.")
    finally:
        pipeline.close()


@app.command("run-all")
def run_all(
    ctx: typer.Context,
    dry_run: bool = True,
    demo: bool = False,
    offline: bool = False,
    auto: bool = False,
) -> None:
    """Run discovery, analysis, tailoring, critic, approval, tracking and follow-up."""
    run_pipeline(ctx, "all", dry_run, demo, offline, auto)


@app.command()
def scout(ctx: typer.Context, demo: bool = False, offline: bool = False) -> None:
    run_pipeline(ctx, "scout", True, demo, offline)


@app.command()
def match(ctx: typer.Context, demo: bool = False, offline: bool = False) -> None:
    run_pipeline(ctx, "match", True, demo, offline)


@app.command()
def tailor(ctx: typer.Context, demo: bool = False, offline: bool = False) -> None:
    run_pipeline(ctx, "tailor", True, demo, offline)


@app.command()
def review(ctx: typer.Context, application_id: str, approve: bool = False) -> None:
    from sqlalchemy.orm import Session

    from lakshya.db.models import ApplicationRecord
    from lakshya.services.lifecycle import transition_status
    from lakshya.services.store import application_files, artifact_hash

    engine = build_engine(current_settings(ctx))
    try:
        with Session(engine) as session, session.begin():
            record = session.get(ApplicationRecord, application_id)
            if record is None:
                raise typer.BadParameter("Application not found")
            console.print(record.critic_report)
            if approve:
                if artifact_hash(application_files(record)) != record.artifact_sha256:
                    raise typer.BadParameter("Artifacts changed after review")
                transition_status(session, record, "approved", source="user", human_approved=True)
                console.print(
                    "Approved. Use lakshya apply APPLICATION_ID to open the local assistant."
                )
    finally:
        engine.dispose()


@app.command()
def apply(
    ctx: typer.Context, application_id: str, dry_run: bool = True, auto: bool = False
) -> None:
    """Open a local browser; final submission requires --no-dry-run and explicit confirmation."""
    import asyncio

    from lakshya.applier import Applier
    from lakshya.services.profile import load_profile
    from lakshya.tracker import Tracker

    settings = current_settings(ctx)
    tracker = Tracker(settings)
    try:
        record = tracker.get(application_id)
        master, profile = load_profile(settings, record.is_demo)
        console.print(
            asyncio.run(
                Applier(settings, tracker).apply(
                    record, profile, master.source_sha256, auto=auto, dry_run=dry_run
                )
            )
        )
    finally:
        tracker.close()


@app.command()
def export(ctx: typer.Context, path: Path = Path("output/applications.xlsx")) -> None:
    from sqlalchemy.orm import Session

    from lakshya.services.exports import export_excel

    engine = build_engine(current_settings(ctx))
    try:
        with Session(engine) as session:
            console.print(str(export_excel(session, path).resolve()))
    finally:
        engine.dispose()


@app.command()
def schedule(ctx: typer.Context, demo: bool = False, offline: bool = False) -> None:
    """Run a dry-run search every day at 09:00 Asia/Kolkata until stopped."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone=current_settings(ctx).timezone)
    scheduler.add_job(
        lambda: run_pipeline(ctx, "all", True, demo, offline),
        "cron",
        hour=9,
        minute=0,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    console.print("Daily search scheduled for 09:00; press Ctrl+C to stop.")
    scheduler.start()
