"""Acceptance tests for spec 002-keep-tasks-in-postgres-and-report-not."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from conftest import ProxiedDb

UNAVAILABLE = {"detail": "Task storage is unavailable."}


def _client(url: str) -> TestClient:
    from demo_taskboard_api.main import create_app

    return TestClient(create_app(database_url=url))


def test_tasks_survive_restart(db_url: str) -> None:  # AC-002.1
    first = _client(db_url)
    created = [
        first.post("/tasks", json={"title": "A"}).json(),
        first.post("/tasks", json={"title": "B", "due_date": "2026-12-01"}).json(),
    ]
    restarted = _client(db_url)
    r = restarted.get("/tasks")
    assert r.status_code == 200
    assert r.json() == created


def test_creation_order_with_rapid_inserts(db_url: str) -> None:  # AC-002.2
    c = _client(db_url)
    created = [c.post("/tasks", json={"title": f"t{i}"}).json() for i in range(30)]
    for _ in range(3):
        assert c.get("/tasks").json() == created


def test_empty_database_lists_empty_array(db_url: str) -> None:  # AC-002.4
    r = _client(db_url).get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


def test_task_visible_on_other_instance(db_url: str) -> None:  # AC-002.5
    one, two = _client(db_url), _client(db_url)
    created = one.post("/tasks", json={"title": "shared", "due_date": "2026-12-01"}).json()
    listed = two.get("/tasks").json()
    assert listed == [created]
    created_two = two.post("/tasks", json={"title": "other"}).json()
    assert one.get("/tasks").json() == [created, created_two]


def test_two_instances_start_together_on_unused_database(db_url: str) -> None:  # AC-002.6
    from demo_taskboard_api.main import create_app

    apps = [create_app(database_url=db_url), create_app(database_url=db_url)]
    barrier = threading.Barrier(2)
    results: list[Any] = [None, None]

    def run(i: int) -> None:
        c = TestClient(apps[i])
        barrier.wait()
        ready = c.get("/ready")
        post = c.post("/tasks", json={"title": f"from-{i}"})
        listing = c.get("/tasks")
        results[i] = (ready.status_code, post.status_code, listing.status_code)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results == [(200, 201, 200), (200, 201, 200)]
    assert len(TestClient(apps[0]).get("/tasks").json()) == 2


def test_different_databases_do_not_share_tasks(  # AC-002.7
    make_db_url: Callable[[], str],
) -> None:
    first, second = _client(make_db_url()), _client(make_db_url())
    assert first.post("/tasks", json={"title": "only here"}).status_code == 201
    assert second.get("/tasks").json() == []


def test_post_while_database_down_is_503(proxied_db: ProxiedDb) -> None:  # AC-002.8
    c = _client(proxied_db.url)
    assert c.get("/tasks").status_code == 200
    proxied_db.down()
    start = time.monotonic()
    r = c.post("/tasks", json={"title": "lost?"})
    assert time.monotonic() - start < 5
    assert r.status_code == 503
    assert r.json() == UNAVAILABLE
    proxied_db.up()
    listed = c.get("/tasks")
    assert listed.status_code == 200
    assert all(t["title"] != "lost?" for t in listed.json())


def test_get_while_database_down_is_503_not_empty_list(  # AC-002.9
    proxied_db: ProxiedDb,
) -> None:
    c = _client(proxied_db.url)
    assert c.post("/tasks", json={"title": "stored"}).status_code == 201
    proxied_db.down()
    start = time.monotonic()
    r = c.get("/tasks")
    assert time.monotonic() - start < 5
    assert r.status_code == 503
    assert r.json() == UNAVAILABLE


def test_503_body_leaks_nothing(proxied_db: ProxiedDb) -> None:  # AC-002.10
    c = _client(proxied_db.url)
    assert c.get("/tasks").status_code == 200
    proxied_db.down()
    for r in (c.get("/tasks"), c.post("/tasks", json={"title": "x"})):
        assert r.status_code == 503
        assert r.json() == UNAVAILABLE
        assert r.headers["content-type"].startswith("application/json")
        for secret in ("127.0.0.1", str(proxied_db.proxy.port), "test", "psycopg", "postgres"):
            assert secret not in r.text.replace("Task storage is unavailable.", "")


def test_ready_with_database_is_200(db_url: str) -> None:  # AC-002.11
    r = _client(db_url).get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_ready_503_fast_and_health_ok_when_database_down(  # AC-002.12
    proxied_db: ProxiedDb,
) -> None:
    c = _client(proxied_db.url)
    assert c.get("/ready").status_code == 200
    proxied_db.down()
    start = time.monotonic()
    r = c.get("/ready")
    assert time.monotonic() - start < 1
    assert r.status_code == 503
    assert r.json() == {"status": "not ready"}
    h = c.get("/health")
    assert h.status_code == 200
    assert h.json() == {"status": "ok"}


def test_recovers_after_outage_without_restart(proxied_db: ProxiedDb) -> None:  # AC-002.13
    c = _client(proxied_db.url)
    before = c.post("/tasks", json={"title": "before"}).json()
    proxied_db.down()
    assert c.get("/ready").status_code == 503
    assert c.get("/tasks").status_code == 503
    proxied_db.up()
    ready = c.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    after = c.post("/tasks", json={"title": "after"})
    assert after.status_code == 201
    assert c.get("/tasks").json() == [before, after.json()]


def test_starts_with_database_down_and_recovers(proxied_db: ProxiedDb) -> None:  # AC-002.14
    proxied_db.down()
    c = _client(proxied_db.url)
    assert c.get("/health").status_code == 200
    assert c.get("/ready").status_code == 503
    proxied_db.up()
    assert c.get("/ready").status_code == 200
    created = c.post("/tasks", json={"title": "late"})
    assert created.status_code == 201
    assert c.get("/tasks").json() == [created.json()]
