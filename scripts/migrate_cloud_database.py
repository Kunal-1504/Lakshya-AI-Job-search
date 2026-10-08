"""Private, verified backup/restore of Lakshya's five cloud tables.

Does not change Vercel, delete source data, migrate Supabase Auth, or publish queue work.
Stop source writes before the final backup/cutover. Credentials come from private env files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

TABLES = {
    "users": (
        "id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "password_hash TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL",
        ("id", "email", "name", "password_hash", "created_at"),
        ("id",),
    ),
    "sessions": (
        "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL",
        ("token_hash", "user_id", "expires_at"),
        ("token_hash",),
    ),
    "attempts": (
        "bucket TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL",
        ("bucket", "created_at"),
        ("bucket", "created_at"),
    ),
    "cloud_files": (
        "user_id TEXT NOT NULL, path TEXT NOT NULL, digest TEXT NOT NULL, contents BYTEA NOT NULL, "
        "mtime DOUBLE PRECISION NOT NULL DEFAULT 0, PRIMARY KEY(user_id,path)",
        ("user_id", "path", "digest", "contents", "mtime"),
        ("user_id", "path"),
    ),
    "cloud_commands": (
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload JSONB NOT NULL, "
        "delay_seconds INTEGER NOT NULL DEFAULT 0, dispatched BOOLEAN NOT NULL DEFAULT FALSE, "
        "done BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ("id", "user_id", "payload", "delay_seconds", "dispatched", "done", "created_at"),
        ("id",),
    ),
}


def schema_name(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("Invalid schema name")
    return value


def settings(path: Path) -> tuple[str, str]:
    values = dotenv_values(path)
    url = values.get("LAKSHYA_POSTGRES_URL") or values.get("POSTGRES_URL_NON_POOLING")
    if not url:
        raise ValueError("Private env file needs a cloud PostgreSQL connection URL")
    return url, schema_name(values.get("LAKSHYA_POSTGRES_SCHEMA") or "public")


def copy_query(schema: str, table: str, *, restore: bool = False) -> sql.Composed:
    columns, ordering = TABLES[table][1:]
    if restore:
        return sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(schema, table), sql.SQL(",").join(map(sql.Identifier, columns))
        )
    return sql.SQL("COPY (SELECT {} FROM {} ORDER BY {}) TO STDOUT").format(
        sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.Identifier(schema, table),
        sql.SQL(",").join(map(sql.Identifier, ordering)),
    )


def configure(db: psycopg.Connection) -> None:
    db.execute("SET TIME ZONE 'UTC'")
    db.execute("SET DateStyle TO 'ISO, YMD'")
    db.execute("SET bytea_output TO 'hex'")


def copy_digest(db: psycopg.Connection, schema: str, table: str, output=None) -> str:
    digest = hashlib.sha256()
    with db.cursor().copy(copy_query(schema, table)) as stream:
        for block in stream:
            digest.update(block)
            if output is not None:
                output.write(block)
    return digest.hexdigest()


def count(db: psycopg.Connection, schema: str, table: str) -> int:
    return db.execute(
        sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(schema, table))
    ).fetchone()[0]


def backup(url: str, schema: str, directory: Path) -> dict:
    # Refuse reuse so a failed retry never overwrites a verified recovery copy.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"format": 1, "created_at": datetime.now(UTC).isoformat(), "tables": {}}
    with psycopg.connect(url, connect_timeout=15) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        configure(db)
        for table in TABLES:
            path = directory / f"{table}.copy"
            with path.open("xb") as output:
                path.chmod(0o600)
                digest = copy_digest(db, schema, table, output)
            manifest["tables"][table] = {
                "rows": count(db, schema, table),
                "sha256": digest,
                "bytes": path.stat().st_size,
            }
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    path.chmod(0o600)
    return manifest


def validate_backup(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != 1 or set(manifest.get("tables", {})) != set(TABLES):
        raise ValueError("Incomplete or unsupported backup")
    for table, details in manifest["tables"].items():
        digest = hashlib.sha256()
        with (directory / f"{table}.copy").open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != details["sha256"]:
            raise ValueError(f"Backup integrity check failed for {table}")
    return manifest


def prepare(db: psycopg.Connection, schema: str) -> None:
    if schema in {"public", "auth", "storage", "extensions", "realtime"}:
        raise ValueError("Restore requires a dedicated private application schema")
    db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    roles = ["PUBLIC"] + [
        row[0]
        for row in db.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role')"
        )
    ]
    for role in roles:
        principal = sql.SQL("PUBLIC") if role == "PUBLIC" else sql.Identifier(role)
        db.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(sql.Identifier(schema), principal)
        )
    for table, (definition, _, _) in TABLES.items():
        db.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
                sql.Identifier(schema, table), sql.SQL(definition)
            )
        )
        db.execute(
            sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                sql.Identifier(schema, table)
            )
        )
        for role in roles:
            principal = sql.SQL("PUBLIC") if role == "PUBLIC" else sql.Identifier(role)
            db.execute(
                sql.SQL("REVOKE ALL ON {} FROM {}").format(sql.Identifier(schema, table), principal)
            )
    db.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS attempt_bucket ON {} (bucket,created_at)").format(
            sql.Identifier(schema, "attempts")
        )
    )
    db.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS cloud_pending ON {} (dispatched,done)").format(
            sql.Identifier(schema, "cloud_commands")
        )
    )


def restore(url: str, schema: str, directory: Path) -> dict:
    manifest = validate_backup(directory)
    with psycopg.connect(url, connect_timeout=15) as db:
        configure(db)
        prepare(db, schema)
        db.execute(
            sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(
                sql.SQL(",").join(sql.Identifier(schema, table) for table in TABLES)
            )
        )
        if any(count(db, schema, table) for table in TABLES):
            raise ValueError("Destination is not empty; refusing to overwrite data")
        for table in TABLES:
            with (directory / f"{table}.copy").open("rb") as source:
                with db.cursor().copy(copy_query(schema, table, restore=True)) as stream:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        stream.write(block)
        verify(db, schema, manifest)
    return manifest


def verify(db: psycopg.Connection, schema: str, manifest: dict) -> None:
    for table, details in manifest["tables"].items():
        if count(db, schema, table) != details["rows"]:
            raise ValueError(f"Row count mismatch for {table}")
        if copy_digest(db, schema, table) != details["sha256"]:
            raise ValueError(f"Restored data mismatch for {table}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore", "verify"])
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        url, schema = settings(args.env_file)
        if args.action == "backup":
            manifest = backup(url, schema, args.directory)
        elif args.action == "restore":
            manifest = restore(url, schema, args.directory)
        else:
            manifest = validate_backup(args.directory)
            with psycopg.connect(url, connect_timeout=15) as db:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                configure(db)
                verify(db, schema, manifest)
        print(
            json.dumps(
                {
                    "action": args.action,
                    "verified": True,
                    "rows": {
                        table: details["rows"] for table, details in manifest["tables"].items()
                    },
                }
            )
        )
        return 0
    except psycopg.Error as exc:
        reason = "quota exceeded" if "quota" in str(exc).lower() else "database unavailable"
        print(f"Migration stopped: {reason}. No cutover performed.", file=sys.stderr)
    except (ValueError, OSError, KeyError) as exc:
        # These errors are generated locally and contain no connection strings.
        print(f"Migration stopped: {type(exc).__name__}. No cutover performed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
