"""Smoke tests for spec 001 (AC-001.1, AC-001.8): reach the service only via its URL."""

from __future__ import annotations

import uuid

import httpx
import pytest


@pytest.mark.smoke
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    r = httpx.post(smoke_base_url + "/tasks", json={"title": title}, timeout=10)
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == title
    assert body["due_date"] is None
    assert body["created_at"]


@pytest.mark.smoke
def test_smoke_ac_001_8_list_tasks(smoke_base_url: str) -> None:  # AC-001.8
    r = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
