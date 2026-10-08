"""Encrypted workspace snapshots, serialized by a distributed PostgreSQL lock.

SQLite remains the local execution format. PostgreSQL is authoritative in cloud mode;
no request or worker may access a tenant outside a locked, freshly restored workspace.
"""

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg import sql
from psycopg.rows import dict_row

_local_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_active: dict[Path, "Workspace"] = {}


def enabled() -> bool:
    return os.getenv("LAKSHYA_CLOUD") == "1"


def connection() -> psycopg.Connection[Any]:
    # A direct connection or session-mode pooler is required for advisory locks.
    # Use our own variable so an old provider integration cannot overwrite the new URL.
    url = os.getenv("LAKSHYA_POSTGRES_URL") or os.environ["POSTGRES_URL_NON_POOLING"]
    schema = os.getenv("LAKSHYA_POSTGRES_SCHEMA", "public")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
        raise ValueError("Invalid cloud database schema")
    db = psycopg.connect(url, row_factory=dict_row, connect_timeout=15)
    try:
        # No public fallback: a missing private schema must never create public tables.
        db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        db.commit()
        return db
    except BaseException:
        db.close()
        raise


def initialize() -> None:
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS cloud_files (
            user_id TEXT NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL, contents BYTEA NOT NULL,
            mtime DOUBLE PRECISION NOT NULL DEFAULT 0, PRIMARY KEY(user_id,path))""")
        db.execute("""CREATE TABLE IF NOT EXISTS cloud_commands (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload JSONB NOT NULL,
            delay_seconds INTEGER NOT NULL DEFAULT 0, dispatched BOOLEAN NOT NULL DEFAULT FALSE,
            done BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        db.execute(
            "ALTER TABLE cloud_files ADD COLUMN IF NOT EXISTS mtime DOUBLE PRECISION NOT NULL DEFAULT 0"
        )
        db.execute("CREATE INDEX IF NOT EXISTS cloud_pending ON cloud_commands(dispatched,done)")


def key() -> AESGCM:
    return AESGCM(base64.urlsafe_b64decode(os.environ["LAKSHYA_STORAGE_KEY"]))


def encrypt(contents: bytes, associated: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + key().encrypt(nonce, contents, associated)


def decrypt(contents: bytes, associated: bytes) -> bytes:
    return key().decrypt(contents[:12], contents[12:], associated)


class Workspace:
    def __init__(self, identity: str, root: Path, db: psycopg.Connection[Any]) -> None:
        self.identity, self.root, self.db = identity, root, db
        self.digests: dict[str, str] = {}
        self.mtimes: dict[str, float] = {}
        self.pending: list[dict[str, Any]] = []
        self.cache = root.parent / ".snapshot-cache" / identity

    def cached_path(self, filename: str, digest: str) -> Path:
        name = hashlib.sha256(filename.encode()).hexdigest()
        return self.cache / f"{name}.{digest}"

    def cache_blob(self, filename: str, digest: str, contents: bytes) -> None:
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.cached_path(filename, digest)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(contents)
        temporary.chmod(0o600)
        temporary.replace(path)

    def restore(self) -> None:
        # Always read authoritative metadata under the account lock. Cached encrypted
        # blobs only save transfer; they never replace the database as the source of truth.
        rows = list(
            self.db.execute(
                "SELECT path,digest,mtime FROM cloud_files WHERE user_id=%s", (self.identity,)
            )
        )
        restored: dict[str, bytes] = {}
        for row in rows:
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid stored file path")
            path = self.cached_path(row["path"], row["digest"])
            try:
                contents = decrypt(path.read_bytes(), f"{self.identity}/{relative}".encode())
                if hashlib.sha256(contents).hexdigest() == row["digest"]:
                    restored[row["path"]] = contents
            except (OSError, InvalidTag, ValueError):
                pass
        missing = [row["path"] for row in rows if row["path"] not in restored]
        if missing:
            for row in self.db.execute(
                "SELECT path,digest,contents FROM cloud_files WHERE user_id=%s AND path=ANY(%s)",
                (self.identity, missing),
            ):
                associated = f"{self.identity}/{row['path']}".encode()
                encrypted = bytes(row["contents"])
                contents = decrypt(encrypted, associated)
                if hashlib.sha256(contents).hexdigest() != row["digest"]:
                    raise ValueError("Stored snapshot integrity check failed")
                restored[row["path"]] = contents
                self.cache_blob(row["path"], row["digest"], encrypted)
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, mode=0o700)
        valid_cache = set()
        for row in rows:
            relative = Path(row["path"])
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(restored[row["path"]])
            path.chmod(0o600)
            if row["mtime"]:
                os.utime(path, (row["mtime"], row["mtime"]))
            self.digests[str(relative)] = row["digest"]
            self.mtimes[str(relative)] = row["mtime"]
            valid_cache.add(self.cached_path(row["path"], row["digest"]))
        if self.cache.exists():
            for path in self.cache.iterdir():
                if path.is_file() and path not in valid_cache:
                    path.unlink()
        self.db.commit()

    def enqueue(self, payload: dict[str, Any], delay: int = 0) -> str:
        identity = str(uuid4())
        self.pending.append({"id": identity, "payload": payload, "delay": delay})
        return identity

    def save(self) -> None:
        files: dict[str, bytes] = {}
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if not path.is_file() or path.is_symlink():
                continue
            if (
                "browser" in relative.parts
                or path.suffix in {".jsonl", ".tmp"}
                or path.name.endswith(("-wal", "-shm"))
            ):
                continue
            if path.suffix == ".sqlite3":
                # Backup includes committed WAL pages, even with other open read connections.
                target = self.root / ".snapshot.tmp"
                with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
                    source.backup(destination)
                files[str(relative)] = target.read_bytes()
                target.unlink()
            else:
                files[str(relative)] = path.read_bytes()
        if sum(map(len, files.values())) > 100 * 1024 * 1024:
            raise ValueError("Account storage limit reached (100 MB)")
        for filename, contents in files.items():
            digest = hashlib.sha256(contents).hexdigest()
            mtime = (self.root / filename).stat().st_mtime
            if digest != self.digests.get(filename):
                encrypted = encrypt(contents, f"{self.identity}/{filename}".encode())
                self.db.execute(
                    """INSERT INTO cloud_files(user_id,path,digest,contents,mtime) VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT(user_id,path) DO UPDATE SET digest=EXCLUDED.digest,contents=EXCLUDED.contents,mtime=EXCLUDED.mtime""",
                    (
                        self.identity,
                        filename,
                        digest,
                        encrypted,
                        (self.root / filename).stat().st_mtime,
                    ),
                )
            elif mtime != self.mtimes.get(filename):
                self.db.execute(
                    "UPDATE cloud_files SET mtime=%s WHERE user_id=%s AND path=%s",
                    (mtime, self.identity, filename),
                )
        for removed in set(self.digests) - files.keys():
            self.db.execute(
                "DELETE FROM cloud_files WHERE user_id=%s AND path=%s", (self.identity, removed)
            )
        from psycopg.types.json import Jsonb

        for command in self.pending:
            self.db.execute(
                """INSERT INTO cloud_commands(id,user_id,payload,delay_seconds)
                VALUES (%s,%s,%s,%s)""",
                (command["id"], self.identity, Jsonb(command["payload"]), command["delay"]),
            )
        self.db.commit()
        self.pending.clear()
        self.mtimes = {name: (self.root / name).stat().st_mtime for name in files}
        self.digests = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


@contextmanager
def workspace(identity: str, root: Path) -> Iterator[Workspace]:
    identity = str(UUID(identity))
    with _locks_guard:
        lock = _local_locks.setdefault(identity, threading.RLock())
    with lock, connection() as db:
        lock_id = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
        db.execute("SET lock_timeout='25s'")
        db.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
        db.commit()
        state = Workspace(identity, root, db)
        try:
            state.restore()
            _active[root.resolve()] = state
            yield state
            state.save()
        finally:
            _active.pop(root.resolve(), None)
            db.rollback()
            db.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
            db.commit()


def active(root: Path) -> Workspace:
    return _active[root.resolve()]


def flush(root: Path) -> None:
    if enabled():
        active(root).save()
