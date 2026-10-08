"""Small DB-API adapter for the shared account store on PostgreSQL."""

import sqlite3
from typing import Any

import psycopg

from lakshya.cloud.store import connection


class Row(dict[str, Any]):
    def __getitem__(self, key: Any) -> Any:
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def fetchone(self) -> Row | None:
        row = self.cursor.fetchone()
        return Row(row) if row else None

    def __iter__(self) -> Any:
        return (Row(row) for row in self.cursor)


class Database:
    def __init__(self) -> None:
        self.db = connection()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, kind: Any, value: Any, traceback: Any) -> None:
        try:
            self.db.rollback() if kind else self.db.commit()
        finally:
            self.db.close()

    def execute(self, sql: str, params: Any = ()) -> Cursor:
        try:
            return Cursor(self.db.execute(sql.replace("?", "%s"), params))
        except psycopg.errors.UniqueViolation as exc:
            raise sqlite3.IntegrityError("Duplicate account") from exc

    def executemany(self, sql: str, params: Any) -> None:
        with self.db.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), params)

    def executescript(self, sql: str) -> None:
        for statement in sql.replace(" REAL ", " DOUBLE PRECISION ").split(";"):
            if statement.strip():
                self.db.execute(statement)
