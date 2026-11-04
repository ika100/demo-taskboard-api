"""Postgres-backed, append-only task store."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text

from .db import Database


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: date | None
    created_at: datetime  # timezone-aware, UTC


TASKS_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title      TEXT        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   DATE        NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
)""",
    "CREATE INDEX IF NOT EXISTS tasks_created_at_seq ON tasks (created_at, seq)",
)

_INSERT = text(
    "INSERT INTO tasks (title, due_date) VALUES (:title, :due_date) "
    "RETURNING id, title, due_date, created_at"
)
_SELECT = text("SELECT id, title, due_date, created_at FROM tasks ORDER BY created_at, seq")


def _to_task(row: Sequence[Any]) -> Task:
    id_, title, due_date, created_at = row
    return Task(
        id=str(id_),
        title=title,
        due_date=due_date,
        created_at=created_at.astimezone(UTC),
    )


class PostgresTaskStore:
    """Tasks in creation order, shared by every instance on the same database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, title: str, due_date: date | None) -> Task:
        with self._db.connection() as conn:
            row = conn.execute(_INSERT, {"title": title, "due_date": due_date}).one()
        return _to_task(row)

    def list(self) -> list[Task]:
        with self._db.connection() as conn:
            rows = conn.execute(_SELECT).all()
        return [_to_task(r) for r in rows]
