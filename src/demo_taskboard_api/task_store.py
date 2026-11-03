"""In-memory, append-only task store."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: date | None
    created_at: datetime  # timezone-aware, UTC


class TaskStore:
    """Thread-safe store of tasks in creation order (per instance)."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: date | None) -> Task:
        with self._lock:
            task = Task(
                id=str(uuid4()),
                title=title,
                due_date=due_date,
                created_at=datetime.now(UTC),
            )
            self._tasks.append(task)
            return task

    def list(self) -> list[Task]:
        with self._lock:
            return self._tasks.copy()
