---
spec_id: 002-keep-tasks-in-postgres-and-report-not
shape: service-python
spec_hash: efbc8855c5c5
summary: Postgres-backed task store (SQLAlchemy Core + psycopg), lazy schema under advisory lock, 503 and honest /ready when the database is unreachable
tasks:
  - id: t1
    title: Add SQLAlchemy, psycopg and testcontainers dependencies
    files: [pyproject.toml, uv.lock]
    covers: [AC-002.1, AC-002.5]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Withdraw AC-001.11 and the in-memory non-goals of spec 001
    files: [docs/specs/001-create-and-list-tasks/spec.md]
    covers: [AC-002.3]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Add the Database module (engine, timeouts, error mapping, readiness, schema bootstrap)
    files: [src/demo_taskboard_api/db.py, tests/test_db.py]
    covers: [AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: false
    depends_on: [t1]
    done: true
  - id: t4
    title: Replace the in-memory TaskStore with PostgresTaskStore
    files: [src/demo_taskboard_api/task_store.py, tests/test_task_store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.7, AC-002.8, AC-002.9]
    parallel_safe: false
    depends_on: [t3]
  - id: t5
    title: Wire the database into create_app, /ready and the 503/500 handlers
    files: [src/demo_taskboard_api/main.py, src/demo_taskboard_api/tasks_api.py, tests/test_health.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.8, AC-002.9, AC-002.10, AC-002.11, AC-002.12, AC-002.13, AC-002.14]
    parallel_safe: false
    depends_on: [t3, t4]
---

# Plan — 002 Keep tasks in Postgres and report not-ready and 503 when the database is unreachable

Design and contract: [design.md](design.md); decision record: [ADR-001](../../adr/001-postgres-access-with-sqlalchemy-core.md). Levels: t1, t2 (parallel) → t3 → t4 → t5.

No gitops task: the system already injects `DATABASE_URL` and `PG*` for this component (`uses: [postgres]`) and probes `/health` and `/ready`.

## t1 — Add SQLAlchemy, psycopg and testcontainers dependencies

**Files:** pyproject.toml, uv.lock
**Covers:** AC-002.1, AC-002.5
**Goal:** the runtime and test dependencies the Postgres store needs, locked.

**Implementation notes:**
- `[project].dependencies`: add `sqlalchemy>=2.0`, `psycopg[binary]>=3.2` (binary wheels: the slim runtime image has no libpq).
- `[project.optional-dependencies].dev`: add `testcontainers[postgres]>=4.8`. If the acceptance-test commit already added it, keep that entry.
- Refresh `uv.lock` through the devbox environment (`devbox run` triggers `uv sync --all-extras` in the init hook); never `uv add` or `pip` directly.
- Check `devbox run audit` is clean with the new packages.

**Done when:** `uv.lock` resolves, `devbox run quality` and `devbox run security` are green, and `import sqlalchemy, psycopg, testcontainers.postgres` works in the devbox env.

## t2 — Withdraw AC-001.11 and the in-memory non-goals of spec 001

**Files:** docs/specs/001-create-and-list-tasks/spec.md
**Covers:** AC-002.3
**Goal:** spec 001 no longer promises an empty list after a restart, so its remaining criteria (the AC-002.3 baseline) and spec 002 do not contradict each other.

**Implementation notes:**
- AC-001.11 becomes `- ~~**AC-001.11**~~ withdrawn 2026-11-04: tasks persist in Postgres (spec 002-keep-tasks-in-postgres-and-report-not, system spec 001-persistent-tasks-and-web-task-list).` (format from the spec reference).
- Strike the non-goals "Persistence beyond the process lifetime …" and "Sharing tasks across multiple replicas …" the same way, with the same reference.
- Remove the `(smoke)` tag from AC-001.8 (its smoke test goes; the list is no longer empty after a deploy). Leave its text otherwise unchanged.
- Changelog line: `2026-11-04 amended: AC-001.11 and two non-goals withdrawn, AC-001.8 no longer smoke (superseded by spec 002).` Do not change `status`.

**Done when:** `devbox run spec-check` reports no error for spec 001.

## t3 — Add the Database module

**Files:** src/demo_taskboard_api/db.py, tests/test_db.py
**Covers:** AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.12, AC-002.13, AC-002.14
**Goal:** one object per app instance that owns the engine, never connects at construction, turns connection-level failures into `StorageUnavailable`, answers readiness within 500 ms and creates the schema once, under an advisory lock, on the first successful connection.

**Implementation notes:**
- Constants and signatures exactly as in design.md (Modules). `normalize_database_url` maps `postgres://`, `postgresql://` and `postgresql+psycopg://` to `postgresql+psycopg://`; anything else raises `ValueError`.
- `Database(url, schema)`: `url is None` = unconfigured (every `connection()` raises `StorageUnavailable`, `is_ready()` is `False`). Otherwise `create_engine` with the settings in design.md; no connection is opened here.
- `connection()`: context manager over `engine.begin()`; before yielding, `_ensure_schema(conn)` if the per-instance flag is unset (a `threading.Lock` around flag check and DDL). DDL transaction: `SELECT pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, then every statement of `schema`, commit, set the flag.
- Error mapping in `connection()` (including errors raised inside the `with` body): `sqlalchemy.exc.OperationalError`, `InterfaceError` and `sqlalchemy.exc.TimeoutError` → `raise StorageUnavailable() from exc`. Everything else propagates.
- `is_ready()`: submit to a `ThreadPoolExecutor(max_workers=2, thread_name_prefix="db-ready")`; worker runs `connection()` with `SET LOCAL statement_timeout = '500ms'` and `SELECT 1`; `future.result(timeout=READY_TIMEOUT_S)`; `False` on timeout or `StorageUnavailable`. Log `readiness_changed` only when the result differs from the previous one.
- `dispose()`: `engine.dispose()` and shut the executor down without waiting.
- Never log or `repr` the URL (it carries the password).
- `tests/test_db.py` (unit, no Docker): URL normalisation cases; unconfigured raises/False; a URL to a closed local port gives `StorageUnavailable` and `is_ready() is False` in under 1 s; the exception message holds no host or password.

**Done when:** `tests/test_db.py` passes and `devbox run quality` is clean. The HTTP acceptance tests pass only after t5.

## t4 — Replace the in-memory TaskStore with PostgresTaskStore

**Files:** src/demo_taskboard_api/task_store.py, tests/test_task_store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.7, AC-002.8, AC-002.9
**Goal:** tasks are stored in and read from the `tasks` table; ids and timestamps come from the database and read back identically.

**Implementation notes:**
- Keep the `Task` dataclass unchanged; remove `TaskStore` and its lock.
- `TASKS_SCHEMA`: the `CREATE TABLE IF NOT EXISTS tasks …` and `CREATE INDEX IF NOT EXISTS …` statements from design.md (Data), as a tuple of strings.
- `PostgresTaskStore(db)`: `add` runs the `INSERT … RETURNING` from design.md inside `db.connection()` and builds a `Task` (`id=str(row.id)`, `created_at` aware datetime); `list` runs the ordered `SELECT` (`ORDER BY created_at, seq`). Bound parameters only (`sqlalchemy.text` with `:title`, `:due_date`), no string formatting.
- Both let `StorageUnavailable` propagate; never return `[]` on failure (AC-002.9).
- Rewrite `tests/test_task_store.py` (it tests the removed in-memory store): use an unconfigured `Database(None, TASKS_SCHEMA)` to check `add`/`list` raise `StorageUnavailable`, and assert the DDL statements are idempotent-form (`IF NOT EXISTS`). Database-backed behaviour is covered by the acceptance tests.

**Done when:** `tests/test_task_store.py` passes and `devbox run quality` is clean.

## t5 — Wire the database into create_app, /ready and the 503/500 handlers

**Files:** src/demo_taskboard_api/main.py, src/demo_taskboard_api/tasks_api.py, tests/test_health.py, docs/env-vars.md
**Covers:** AC-002.1 to AC-002.14
**Goal:** every app instance talks to the database named by its URL, answers `503` with the fixed body when storage is unavailable, reports readiness from a live check, and starts without a database.

**Implementation notes:**
- `create_app(database_url: str | None = None)`: `url = database_url or os.environ.get("DATABASE_URL") or None`; `app.state.database = Database(url, TASKS_SCHEMA)`; `app.state.task_store = PostgresTaskStore(app.state.database)`. Log `database_unconfigured` (warning) when `url` is None. `app = create_app()` stays the uvicorn entry point.
- Lifespan: on shutdown `app.state.database.dispose()`; nothing on startup (startup must not need the database, AC-002.14).
- `/ready`: `200 {"status": "ready"}` when `request.app.state.database.is_ready()`, else `JSONResponse(503, {"status": "not ready"})`. `/health` unchanged.
- Exception handler for `StorageUnavailable`: log `task_storage_unavailable` with `error_type=type(exc.__cause__).__name__` and `error=str(exc.__cause__)`; return `JSONResponse(503, {"detail": "Task storage is unavailable."})`.
- Exception handler for `Exception`: `JSONResponse(500, {"detail": "Internal Server Error"})`. The existing metrics test (`/boom` counted as 500 with `application_errors_total`) must keep passing.
- `tasks_api.py`: `get_task_store` returns `PostgresTaskStore`; routes, schemas and the `task_created` log stay as they are. Handlers stay sync `def` (they run in the thread pool; the driver is sync).
- `tests/test_health.py`: `test_ready_returns_ready` now uses the unconfigured module-level `app`, so change it to expect `503 {"status": "not ready"}`; the `200` case is the AC-002.11 acceptance test.
- `docs/env-vars.md`: new "Database" section with `DATABASE_URL` (required in a deployment, injected by the gitops repo, accepted schemes, never logged; `PG*` present but unused).

**Done when:** every acceptance test for AC-002.1 to AC-002.14 and the ported spec 001 tests pass, the health/metrics/tracing tests pass, and `devbox run ci` is green (coverage gate included).
