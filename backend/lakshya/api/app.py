import hmac
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

import structlog
from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from sqlalchemy import func, inspect, select

from lakshya.config import Settings, load_settings
from lakshya.db.models import ApplicationRecord, JobRecord
from lakshya.db.session import build_engine, session_factory
from lakshya.logging import configure_logging

header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings: Settings | None = None, *, account_workspace: bool = False) -> FastAPI:
    settings = settings or load_settings()
    expected_key = settings.api_key.get_secret_value()
    if not expected_key:
        raise ValueError("Set LAKSHYA_API_KEY before starting the API")
    if not account_workspace:
        configure_logging(settings.log_file)
    log = structlog.get_logger("lakshya.api")
    engine = build_engine(settings)
    factory = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not account_workspace:
            import asyncio

            await asyncio.to_thread(accounts.start)
        manager.start_scheduler()
        log.info("api_started", environment=settings.environment)
        yield
        if not account_workspace:
            accounts.close()
        manager.close()
        engine.dispose()
        log.info("api_stopped")

    app = FastAPI(
        title="Lakshya",
        version="1.0.0",
        lifespan=lifespan,
        description="Live job discovery, evidence-based applications, review and tracking.",
    )
    app.state.engine = engine
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next: Any) -> Response:
        request_id = str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    def authenticate(key: Annotated[str | None, Security(header)] = None) -> None:
        if key is None or not hmac.compare_digest(
            key.encode("utf-8"), expected_key.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/health", tags=["Infrastructure"])
    def health() -> dict[str, Any]:
        try:
            with engine.connect() as connection:
                revision = MigrationContext.configure(connection).get_current_revision()
            if not revision:
                raise HTTPException(status_code=503, detail="Run lakshya init-db first")
            return {
                "status": "ok",
                "database": "ready",
                "schema_revision": revision,
                "environment": settings.environment,
            }
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("database_health_failed", error_type=type(exc).__name__)
            raise HTTPException(status_code=503, detail="Database unavailable") from exc

    router = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    @router.get("/foundation", tags=["Infrastructure"])
    def foundation() -> dict[str, Any]:
        health()
        with factory() as session:
            jobs = list(session.scalars(select(JobRecord).order_by(JobRecord.created_at)))
            applications = session.scalar(select(func.count()).select_from(ApplicationRecord)) or 0
            return {
                "phase": 1,
                "version": "0.1.0",
                "settings": settings.public_summary(),
                "tables": inspect(engine).get_table_names(),
                "counts": {
                    "jobs": len(jobs),
                    "applications": applications,
                    "demo_jobs": sum(job.is_demo for job in jobs),
                },
                "jobs": [
                    {
                        "id": job.id,
                        "title": job.title,
                        "company": job.company,
                        "location": job.location,
                        "source": job.source,
                        "is_demo": job.is_demo,
                        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
                    }
                    for job in jobs
                ],
            }

    from lakshya.api.routes import install_routes

    manager = install_routes(router, settings, factory)
    app.state.run_manager = manager
    app.include_router(router)
    if not account_workspace:
        from lakshya.api.accounts import AccountGateway, Accounts, install_accounts

        accounts = Accounts(settings, lambda isolated: create_app(isolated, account_workspace=True))
        app.state.accounts = accounts
        install_accounts(app, accounts)
        app.add_middleware(AccountGateway, accounts=accounts)
    return app
