"""Acceptance tests for spec 001-create-and-list-tasks, run against a real database.

They are the AC-002.3 baseline: the 001 behaviour must be unchanged with Postgres behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def fresh(db_url: str) -> TestClient:
    """A TestClient over a new app instance on a brand-new, empty database."""
    from demo_taskboard_api.main import create_app

    return TestClient(create_app(database_url=db_url))


def _names_field(response: Any, field: str) -> bool:
    detail = response.json()["detail"]
    return bool(detail) and any(str(e["loc"][-1]) == field for e in detail)


def test_create_task_returns_201_body(fresh: TestClient) -> None:  # AC-001.1 AC-002.3
    r = fresh.post("/tasks", json={"title": "Buy milk"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None
    created = datetime.fromisoformat(body["created_at"])
    assert created.utcoffset() == timedelta(0)
    assert created.tzinfo is not None and created.astimezone(UTC)


def test_create_task_with_due_date(fresh: TestClient) -> None:  # AC-001.2 AC-002.3
    r = fresh.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-01"})
    assert r.status_code == 201
    assert r.json()["due_date"] == "2026-12-01"


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": None}, {"title": ""}, {"title": "   "}],
)
def test_invalid_title_rejected(  # AC-001.3 AC-002.3
    fresh: TestClient, payload: dict[str, Any]
) -> None:
    r = fresh.post("/tasks", json=payload)
    assert r.status_code == 422
    assert _names_field(r, "title")
    assert fresh.get("/tasks").json() == []


def test_title_length_limit(fresh: TestClient) -> None:  # AC-001.4 AC-002.3
    r = fresh.post("/tasks", json={"title": "a" * 201})
    assert r.status_code == 422
    assert _names_field(r, "title")
    r = fresh.post("/tasks", json={"title": "  " + "a" * 201 + "  "})
    assert r.status_code == 422
    assert len(fresh.get("/tasks").json()) == 0
    r = fresh.post("/tasks", json={"title": "a" * 200})
    assert r.status_code == 201
    r = fresh.post("/tasks", json={"title": " " + "a" * 200 + " "})
    assert r.status_code == 201


def test_title_is_trimmed(fresh: TestClient) -> None:  # AC-001.5 AC-002.3
    r = fresh.post("/tasks", json={"title": "  Buy milk  "})
    assert r.status_code == 201
    assert r.json()["title"] == "Buy milk"
    assert fresh.get("/tasks").json()[0]["title"] == "Buy milk"


@pytest.mark.parametrize("due", ["tomorrow", "2026-13-01", "2026-02-30", "2026-12-01T10:00:00Z"])
def test_invalid_due_date_rejected(fresh: TestClient, due: str) -> None:  # AC-001.6 AC-002.3
    r = fresh.post("/tasks", json={"title": "x", "due_date": due})
    assert r.status_code == 422
    assert _names_field(r, "due_date")
    assert fresh.get("/tasks").json() == []


def test_past_due_date_accepted(fresh: TestClient) -> None:  # AC-001.7 AC-002.3
    r = fresh.post("/tasks", json={"title": "old", "due_date": "2000-01-01"})
    assert r.status_code == 201
    assert r.json()["due_date"] == "2000-01-01"


def test_list_empty_on_fresh_database(fresh: TestClient) -> None:  # AC-001.8 AC-002.4
    r = fresh.get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


def test_list_in_creation_order(fresh: TestClient) -> None:  # AC-001.9 AC-002.3
    a = fresh.post("/tasks", json={"title": "A"}).json()
    b = fresh.post("/tasks", json={"title": "B", "due_date": "2026-12-01"}).json()
    r = fresh.get("/tasks")
    assert r.status_code == 200
    assert r.json() == [a, b]


def test_same_title_gets_distinct_ids(fresh: TestClient) -> None:  # AC-001.10 AC-002.3
    r1 = fresh.post("/tasks", json={"title": "same"})
    r2 = fresh.post("/tasks", json={"title": "same"})
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
    assert len(fresh.get("/tasks").json()) == 2
