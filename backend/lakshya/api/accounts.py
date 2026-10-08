"""Password accounts, opaque sessions, and isolated per-account application workspaces."""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from lakshya.cloud import store as cloud
from lakshya.config import Settings
from lakshya.db.migrate import upgrade_database

COOKIE = "lakshya_session"
SESSION_SECONDS = 7 * 24 * 3600


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64 * 1024 * 1024
    ).hex()
    return f"scrypt${salt}${digest}"


def check_password(password: str, encoded: str) -> bool:
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(password_hash(password, salt), encoded)


class AccountInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(default="", max_length=100)


class Accounts:
    def __init__(self, settings: Settings, build: Callable[[Settings], FastAPI]) -> None:
        self.settings, self.build = settings, build
        self.path = settings.data_dir / "accounts.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.apps: dict[str, FastAPI] = {}
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    password_hash TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (bucket TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS attempt_bucket ON attempts(bucket, created_at);
            """)
        if not cloud.enabled():
            os.chmod(self.path, 0o600)
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    def db(self) -> Any:
        if cloud.enabled():
            from lakshya.cloud.auth import Database

            return Database()
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def rate_limit(self, request: Request, email: str) -> None:
        address = request.headers.get("x-real-ip") or (
            request.client.host if request.client else ""
        )
        now = time.time()
        # Bound both per-address bursts and distributed attacks on a single account.
        buckets = [hashlib.sha256(value.encode()).hexdigest() for value in (address, email)]
        with self.lock, self.db() as db:
            if cloud.enabled():
                for bucket in sorted(buckets):
                    db.execute("SELECT pg_advisory_xact_lock(?)", (int(bucket[:15], 16),))
            db.execute("DELETE FROM attempts WHERE created_at < ?", (now - 600,))
            for bucket in buckets:
                count = db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE bucket=? AND created_at>?",
                    (bucket, now - 60),
                ).fetchone()[0]
                if count >= 10:
                    raise HTTPException(429, "Too many attempts. Please try again in a minute.")
            db.executemany("INSERT INTO attempts VALUES (?, ?)", [(b, now) for b in buckets])

    def user(self, token: str | None) -> dict[str, str] | None:
        if not token or len(token) > 256:
            return None
        with self.db() as db:
            row = db.execute(
                "SELECT u.id,u.email,u.name FROM users u JOIN sessions s ON u.id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        return dict(row) if row else None

    def session(self, response: Response, user_id: str) -> None:
        token = secrets.token_urlsafe(48)
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    user_id,
                    time.time() + SESSION_SECONDS,
                ),
            )
        response.set_cookie(
            COOKIE,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    def workspace(self, identity: str) -> FastAPI:
        with self.lock:
            if identity in self.apps:
                return self.apps[identity]
            directory = self.settings.data_dir / "accounts" / identity
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            config = directory / "config.yaml"
            data = (
                yaml.safe_load(config.read_text())
                if config.exists()
                else {
                    **self.settings.model_dump(mode="json"),
                    "ai_provider": "local",
                    "application_mode": "assist",
                    "live_search_enabled": False,
                    "answers": {},
                    "form_selectors": {},
                }
            )
            data.update(
                {
                    "data_dir": str(directory),
                    "output_dir": str(directory / "output"),
                    "database_url": f"sqlite:///{directory / 'workspace.sqlite3'}",
                    "log_file": str(directory / "events.jsonl"),
                    "browser_profile": str(directory / "browser"),
                    "browser_headless": True,
                }
            )
            # No account inherits the owner's personal AI credentials or screening answers.
            private = directory / "credentials.json"
            credentials = json.loads(private.read_text()) if private.exists() else {}
            isolated = Settings.model_validate(
                data
                | {
                    "config_file": config,
                    "api_key": SecretStr(secrets.token_urlsafe(48)),
                    "gemini_api_key": SecretStr(credentials.get("GEMINI_API_KEY", "")),
                    "anthropic_api_key": SecretStr(credentials.get("ANTHROPIC_API_KEY", "")),
                    "adzuna_app_id": SecretStr(credentials.get("ADZUNA_APP_ID", "")),
                    "adzuna_app_key": SecretStr(credentials.get("ADZUNA_APP_KEY", "")),
                }
            )
            if not config.exists():
                config.write_text(yaml.safe_dump(isolated.model_dump(mode="json"), sort_keys=False))
            upgrade_database(isolated)
            app = self.build(isolated)
            if not cloud.enabled():
                app.state.run_manager.start_scheduler()
            self.apps[identity] = app
            return app

    def start(self) -> None:
        if cloud.enabled():
            return
        with self.db() as db:
            identities = [row[0] for row in db.execute("SELECT id FROM users")]
        for identity in identities:
            config = self.settings.data_dir / "accounts" / identity / "config.yaml"
            if config.exists() and (yaml.safe_load(config.read_text()) or {}).get(
                "live_search_enabled"
            ):
                self.workspace(identity)

    def close(self) -> None:
        for app in self.apps.values():
            app.state.run_manager.close()
            app.state.engine.dispose()


def install_accounts(app: FastAPI, accounts: Accounts) -> None:
    @app.post("/api/auth/signup", status_code=201)
    def signup(body: AccountInput, request: Request, response: Response) -> dict[str, str]:
        email = body.email.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise HTTPException(422, "Enter a valid email address.")
        if not body.name.strip():
            raise HTTPException(422, "Enter your name.")
        accounts.rate_limit(request, email)
        identity = str(uuid4())
        digest = password_hash(body.password)
        try:
            with accounts.db() as db:
                db.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    (identity, email, body.name.strip(), digest, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "This email already has an account. Sign in instead.") from exc
        accounts.session(response, identity)
        return {"id": identity, "email": email, "name": body.name.strip()}

    @app.post("/api/auth/signin")
    def signin(body: AccountInput, request: Request, response: Response) -> dict[str, str]:
        email = body.email.strip().lower()
        accounts.rate_limit(request, email)
        with accounts.db() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        valid = check_password(body.password, row["password_hash"] if row else accounts.dummy_hash)
        if not row or not valid:
            raise HTTPException(401, "Email or password is incorrect.")
        accounts.session(response, row["id"])
        return {key: row[key] for key in ("id", "email", "name")}

    @app.get("/api/auth/me")
    def me(request: Request, response: Response) -> dict[str, str]:
        user = accounts.user(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Please sign in.")
        response.headers["Cache-Control"] = "no-store"
        return user

    @app.post("/api/auth/signout")
    def signout(request: Request, response: Response) -> dict[str, bool]:
        token = request.cookies.get(COOKIE, "")
        with accounts.db() as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
        response.delete_cookie(
            COOKIE, path="/", secure=accounts.settings.cookie_secure, httponly=True, samesite="lax"
        )
        response.headers["Cache-Control"] = "no-store"
        return {"signed_out": True}


class AccountGateway:
    """Dispatch authenticated business requests into a user's isolated application."""

    def __init__(self, app: ASGIApp, accounts: Accounts) -> None:
        self.app, self.accounts = app, accounts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = request.cookies.get(COOKIE)
        # JSON auth forms and all cookie-authenticated writes enforce same-origin requests.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            token or scope["path"].startswith("/api/auth/")
        ):
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.headers.get("host", "")
            ):
                await JSONResponse({"detail": "Cross-site request rejected."}, status_code=403)(
                    scope, receive, send
                )
                return
        if scope["path"].startswith("/api/auth/"):
            await self.app(scope, receive, send)
            return
        user = self.accounts.user(token)
        if not user:
            # Private operator API remains available for CLI and migration; never sent to browsers.
            await self.app(scope, receive, send)
            return
        import asyncio

        if cloud.enabled():

            def serve() -> list[Any]:
                messages: list[Any] = []

                async def collect(message: Any) -> None:
                    messages.append(message)

                directory = self.accounts.settings.data_dir / "accounts" / user["id"]
                with cloud.workspace(user["id"], directory):
                    tenant = self.accounts.workspace(user["id"])
                    child_scope = dict(scope)
                    child_scope["headers"] = [
                        (k, v) for k, v in scope["headers"] if k.lower() != b"x-api-key"
                    ] + [(b"x-api-key", tenant.state.settings.api_key.get_secret_value().encode())]
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            tenant(child_scope, receive, collect), loop
                        )
                        future.result()
                    finally:
                        tenant.state.run_manager.close()
                        tenant.state.engine.dispose()
                        self.accounts.apps.pop(user["id"], None)
                return messages

            loop = asyncio.get_running_loop()
            try:
                messages = await asyncio.to_thread(serve)
            except Exception as exc:
                import structlog

                structlog.get_logger("lakshya.cloud").warning(
                    "workspace_unavailable", error_type=type(exc).__name__
                )
                await JSONResponse(
                    {
                        "detail": "Your workspace is busy or temporarily unavailable. Please try again."
                    },
                    status_code=503,
                )(scope, receive, send)
                return
            for message in messages:
                await send(message)
            return
        tenant = await asyncio.to_thread(self.accounts.workspace, user["id"])
        child_scope = dict(scope)
        child_scope["headers"] = [
            (k, v) for k, v in scope["headers"] if k.lower() != b"x-api-key"
        ] + [(b"x-api-key", tenant.state.settings.api_key.get_secret_value().encode())]
        await tenant(child_scope, receive, send)
