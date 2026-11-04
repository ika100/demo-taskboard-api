"""Unit tests for PostgresTaskStore that need no database."""

from __future__ import annotations

import pytest

from demo_taskboard_api.db import Database, StorageUnavailable
from demo_taskboard_api.task_store import TASKS_SCHEMA, PostgresTaskStore


def test_unconfigured_store_raises_on_add_and_list() -> None:
    store = PostgresTaskStore(Database(None, TASKS_SCHEMA))
    with pytest.raises(StorageUnavailable):
        store.add("A", None)
    with pytest.raises(StorageUnavailable):
        store.list()


def test_schema_is_idempotent() -> None:
    assert TASKS_SCHEMA
    for statement in TASKS_SCHEMA:
        assert "IF NOT EXISTS" in statement
