"""Private Vercel container entrypoint, accessed only through a server binding."""

import asyncio
import hmac
import logging
import os
from collections.abc import Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class PrivateGateway:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            supplied = headers.get(b"x-lakshya-service", b"")
            if not hmac.compare_digest(supplied, os.environ["LAKSHYA_SERVICE_KEY"].encode()):
                await JSONResponse({"detail": "Private service"}, status_code=401)(
                    scope, receive, send
                )
                return
            public_host = headers.get(b"x-lakshya-public-host")
            if public_host:
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"host"] + [
                    (b"host", public_host)
                ]
        await self.app(scope, receive, send)


def build() -> Any:
    # Heavy imports and database initialization must happen after the container
    # has bound its listening port, not during Uvicorn's module import/startup.
    from pydantic import SecretStr

    from lakshya.api.app import create_app
    from lakshya.cloud import store
    from lakshya.cloud.worker import process
    from lakshya.config import load_settings
    from lakshya.db.migrate import upgrade_database

    settings = load_settings()
    settings.api_key = SecretStr(os.environ["LAKSHYA_SERVICE_KEY"])
    settings.embedding_backend = "lexical"
    settings.environment = "production"
    settings.cookie_secure = True
    settings.live_search_enabled = False
    settings.ai_provider = "local"
    settings.max_pages = 1
    settings.max_jobs_per_source = 40
    settings.http_timeout = 15
    upgrade_database(settings)
    store.initialize()
    app = create_app(settings)
    app.add_middleware(PrivateGateway)

    @app.get("/internal/outbox")
    def outbox() -> list[dict[str, Any]]:
        with store.connection() as db:
            return list(
                db.execute("""SELECT id,delay_seconds FROM cloud_commands
                WHERE NOT dispatched AND NOT done ORDER BY created_at LIMIT 20""")
            )

    @app.post("/internal/dispatched")
    def dispatched(body: dict[str, Any]) -> dict[str, bool]:
        with store.connection() as db:
            db.execute("UPDATE cloud_commands SET dispatched=TRUE WHERE id=%s", (body["id"],))
        return {"saved": True}

    @app.post("/internal/step")
    def step(body: dict[str, Any]) -> dict[str, bool]:
        return process(app.state.accounts, body["id"])

    @app.post("/internal/recover")
    def recover() -> dict[str, bool]:
        with store.connection() as db:
            # Queue retention is seven days. Recover deliveries missed beyond that window.
            db.execute("""UPDATE cloud_commands SET dispatched=FALSE
                WHERE NOT done AND created_at < NOW()-INTERVAL '7 days'""")
            db.execute(
                "DELETE FROM cloud_commands WHERE done AND created_at<NOW()-INTERVAL '7 days'"
            )
        return {"ready": True}

    return app


class ReadyCloudApp:
    """Bind immediately; initialize once on an authenticated request, with full lifespan."""

    def __init__(self, builder: Callable[[], Any] = build) -> None:
        self.builder = builder
        self.application: Any = None
        self.context: Any = None
        self.lock = asyncio.Lock()

    async def initialize(self) -> Any:
        async with self.lock:
            if self.application is None:
                application = await asyncio.to_thread(self.builder)
                context = application.router.lifespan_context(application)
                await context.__aenter__()
                self.application, self.context = application, context
        return self.application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    # No external I/O before the port is opened. Real initialization
                    # still finishes before any authenticated request is dispatched.
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    async with self.lock:
                        if self.context:
                            await self.context.__aexit__(None, None, None)
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            expected = os.environ.get("LAKSHYA_SERVICE_KEY", "")
            supplied = dict(scope.get("headers", [])).get(b"x-lakshya-service", b"")
            if not expected or not hmac.compare_digest(supplied, expected.encode()):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse({"detail": "Private service"}, status_code=401)(
                        scope, receive, send
                    )
                return
            try:
                application = await self.initialize()
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "Cloud initialization failed: %s", type(exc).__name__
                )
                await JSONResponse(
                    {"detail": "Cloud service is temporarily unavailable. Please retry."},
                    status_code=503,
                    headers={"Retry-After": "5"},
                )(scope, receive, send)
                return
            await application(scope, receive, send)


app = ReadyCloudApp()
