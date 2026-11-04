# Design — 002 Keep tasks in Postgres and report not-ready and 503 when the database is unreachable

## Decisions

- **SQLAlchemy 2 Core on psycopg 3, pool with pre-ping, no in-API retries.** Connections are opened on demand in the request thread; a broken one is dropped at checkout and replaced on the next request, so recovery after an outage needs no restart and no background reconnect loop (AC-002.13, AC-002.14). ADR: [docs/adr/001-postgres-access-with-sqlalchemy-core.md](../../adr/001-postgres-access-with-sqlalchemy-core.md).
- **Timeouts are constants**: connect 2 s, statement 3 s, `tcp_user_timeout` 3 s, pool checkout 3 s, readiness budget 500 ms. Only `DATABASE_URL` is configuration (non-goal: no other DB settings).
- **One `Database` per app instance** (`db.py`) owns the engine, the error mapping to `StorageUnavailable`, the readiness ping and the lazy schema bootstrap. `PostgresTaskStore` (`task_store.py`) holds the SQL for tasks. The router and the readiness handler talk only to these two.
- **Schema created lazily under an advisory lock.** The first operation that gets a connection (a task call or `/ready`) runs the DDL in one transaction after `SELECT pg_advisory_xact_lock(2002001)`; a per-instance flag (guarded by a `threading.Lock`) skips it afterwards. Two replicas starting together serialize on the lock and both succeed (AC-002.6). Startup never touches the database, so the service starts while Postgres is down (AC-002.14).
- **`created_at` and `id` come from the database** (`clock_timestamp()`, `gen_random_uuid()`), returned with `INSERT … RETURNING`. One clock for all replicas keeps the cross-instance order consistent; the value returned at creation is the one stored, so later reads are identical (AC-002.1, AC-002.5). Order is `created_at, seq` where `seq` is an identity column, so equal timestamps keep insertion order (AC-002.2).
- **Error mapping**: `sqlalchemy.exc.OperationalError`, `sqlalchemy.exc.InterfaceError` and the pool's `sqlalchemy.exc.TimeoutError` (connection refused, connect timeout, statement timeout, connection lost) become `StorageUnavailable`; one exception handler answers it with `503 {"detail": "Task storage is unavailable."}` and logs the driver error. Every other exception is a `500` with `{"detail": "Internal Server Error"}` (contract). The response never carries driver text (AC-002.10).
- **Unconfigured is a state, not a crash.** Without a URL (`create_app()` with no argument and no `DATABASE_URL`), the app starts; task routes answer `503`, `/ready` answers `503`, `/health` `200`. This keeps `from demo_taskboard_api.main import app` importable in tests and in the image without a database.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/demo_taskboard_api/db.py` | URL normalisation, engine factory with the timeout constants, `StorageUnavailable`, `Database` (`connection()`, `is_ready()`, lazy schema bootstrap under advisory lock) | new |
| `src/demo_taskboard_api/task_store.py` | `Task` record (unchanged), `TASKS_SCHEMA` DDL, `PostgresTaskStore` (`add`, `list`) on a `Database`; the in-memory `TaskStore` is removed | changed |
| `src/demo_taskboard_api/tasks_api.py` | same routes and schemas; `get_task_store` returns the `PostgresTaskStore` | changed |
| `src/demo_taskboard_api/main.py` | `create_app(database_url=None)`, `/ready` backed by `Database.is_ready()`, `StorageUnavailable` → 503 handler, JSON 500 handler, lifespan disposes the engine | changed |
| `pyproject.toml`, `uv.lock` | runtime `sqlalchemy>=2.0`, `psycopg[binary]>=3.2`; dev `testcontainers[postgres]>=4.8` | changed |

Public interfaces (signatures only):

```python
# db.py
CONNECT_TIMEOUT_S = 2
STATEMENT_TIMEOUT_MS = 3000
POOL_TIMEOUT_S = 3
READY_TIMEOUT_S = 0.5
SCHEMA_LOCK_KEY = 2002001

class StorageUnavailable(Exception): ...          # carries the original exception as __cause__

def normalize_database_url(url: str) -> str: ...  # postgres:// | postgresql:// | postgresql+psycopg:// -> postgresql+psycopg://

class Database:
    def __init__(self, url: str | None, schema: Sequence[str]) -> None: ...  # never connects; url None = unconfigured
    @contextmanager
    def connection(self) -> Iterator[Connection]: ...  # begin() transaction; ensures schema first; maps errors to StorageUnavailable
    def is_ready(self) -> bool: ...                    # SELECT 1 + ensure schema, in a worker thread, False after READY_TIMEOUT_S
    def dispose(self) -> None: ...

# task_store.py
@dataclass(frozen=True)
class Task:                                         # unchanged
    id: str; title: str; due_date: date | None; created_at: datetime

TASKS_SCHEMA: tuple[str, ...]

class PostgresTaskStore:
    def __init__(self, db: Database) -> None: ...
    def add(self, title: str, due_date: date | None) -> Task: ...   # raises StorageUnavailable
    def list(self) -> list[Task]: ...                               # ORDER BY created_at, seq; raises StorageUnavailable

# main.py
def create_app(database_url: str | None = None) -> FastAPI: ...  # explicit url wins, else os.environ["DATABASE_URL"], else unconfigured
app: FastAPI                                                       # = create_app()
```

`app.state.database` holds the `Database`, `app.state.task_store` the `PostgresTaskStore`.

Engine settings (`create_engine`): `pool_pre_ping=True`, `pool_size=5`, `max_overflow=5`, `pool_timeout=POOL_TIMEOUT_S`, `pool_recycle=1800`, `connect_args={"connect_timeout": 2, "options": "-c statement_timeout=3000", "tcp_user_timeout": 3000}`. `is_ready` runs on a per-`Database` `ThreadPoolExecutor(max_workers=2)` and waits `future.result(timeout=READY_TIMEOUT_S)`; inside it, `SET LOCAL statement_timeout = '500ms'` before `SELECT 1`. A timeout or any `StorageUnavailable` returns `False`.

## Contract

Unchanged for clients from spec 001 (fields, trimming, limits, 422 format, see [001 design](../001-create-and-list-tasks/design.md#contract)) except where stated. Binding for the acceptance tests:

### `POST /tasks`

- `201`: task object `{"id": str, "title": str, "due_date": "YYYY-MM-DD" | null, "created_at": "<ISO 8601 UTC>Z"}`. `id` is a UUID string (opaque to clients). `created_at` has microsecond precision; it is identical on every later read (AC-002.1).
- `422`: FastAPI validation body, `loc[-1]` is `title` or `due_date` (AC-002.3). Validation runs before any database access, so a `422` is returned even while the database is down.
- `503`: database unreachable, body exactly `{"detail": "Task storage is unavailable."}`, `Content-Type: application/json`, within 5 s; no task stored (AC-002.8, AC-002.10).

### `GET /tasks`

- `200`: JSON array of task objects, `ORDER BY created_at, seq` (oldest first, AC-002.2). `[]` only when the table is empty (AC-002.4).
- `503`: as above, never `200 []` while the database is unreachable (AC-002.9, AC-002.10).

### `GET /ready`

- `200 {"status": "ready"}`: `SELECT 1` succeeded and the schema exists (AC-002.11, AC-002.6).
- `503 {"status": "not ready"}`: unconfigured, unreachable, or the check exceeded 500 ms; answered within 1 s (AC-002.12). Evaluated on every call (AC-002.13, AC-002.14).

### `GET /health`

`200 {"status": "ok"}` always; never touches the database (AC-002.12, AC-002.14).

### `500`

Any unexpected exception: `500 {"detail": "Internal Server Error"}` (JSON).

### Configuration

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes in a deployment | `postgresql://user:pass@host:port/db` (also `postgres://`, `postgresql+psycopg://`); injected by the gitops repo from the CloudNativePG Secret. Never logged. `PG*` are present but not read. |

### Test harness (for the acceptance tests)

- `create_app(database_url=...)` is the only way tests point an instance at a database; tests must not set `DATABASE_URL` in `os.environ` (the module-level `app` used by `tests/conftest.py`'s `client` stays unconfigured, so its `/ready` answers `503`).
- One Postgres per test session from `testcontainers.postgres.PostgresContainer("postgres:16-alpine", driver=None)`; each test that needs a known list gets a fresh database (`CREATE DATABASE t_<uuid>` on the container) so AC-002.4 sees `[]` and AC-002.7 has two independent databases.
- "Restart" (AC-002.1) = a new `create_app(url)` on the same URL; "two instances" (AC-002.5, AC-002.6) = two `create_app(url)` on the same URL; "start together" (AC-002.6) = first calls on both from two threads against a never-used database.
- Outage (AC-002.8, AC-002.9, AC-002.12 to AC-002.14) = an in-test TCP proxy between the app and the container that can be stopped (close the listener and every open connection) and restarted on the same port. "Database down at startup" (AC-002.14) = the proxy is stopped before `create_app`. An unreachable URL is also fine for the pure-down cases: `postgresql://u:p@127.0.0.1:<closed port>/db`.
- Spec 001 acceptance tests in `tests/test_tasks.py` must move to the DB-backed fresh-database fixture (they are the AC-002.3 baseline); `test_restart_empties_list` (AC-001.11, withdrawn) goes, and the AC-001.8 smoke test in `tests/test_smoke_tasks.py` goes (the list is not empty after a deploy). AC-002.11 gets a smoke test (`GET /ready` → `200 {"status": "ready"}`).

## Data

Table `tasks`, created by `TASKS_SCHEMA` (idempotent):

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    title      TEXT        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   DATE        NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS tasks_created_at_seq ON tasks (created_at, seq);
```

Insert: `INSERT INTO tasks (title, due_date) VALUES (:title, :due_date) RETURNING id, title, due_date, created_at`. List: `SELECT id, title, due_date, created_at FROM tasks ORDER BY created_at, seq`. `id` is returned to clients as `str(uuid)`. No carry-over of in-memory tasks (non-goal). Each environment has its own CloudNativePG cluster and so its own `tasks` table (AC-002.7, system AC-001.5).

## Observability

- `task_created` (unchanged: `task_id`, `has_due_date`).
- `task_storage_unavailable` (warning) from the 503 handler: `error_type` (driver exception class) and `error` (driver message). Never the URL or credentials.
- `readiness_changed` (info/warning) only when `is_ready()` flips, so probes every few seconds do not flood the log.
- Request metrics come from the existing middleware; `503`s show under `status_code="503"`.

## Risks

- **Image smoke without a database**: the platform script `scripts/image-smoke.sh` runs the image without Postgres and `curl -f`s `/ready`, `POST /tasks` and `GET /tasks`; after this spec those answer `503`, so the script fails. It is platform-owned (not editable here): propose a change through `/issue:report` (run it with a Postgres sidecar, or only require `/health`).
- **Docker needed for `devbox run test`** (testcontainers). GitHub-hosted runners have it; a self-hosted `CI_RUNNER` must too.
- **Silent network partition**: a pooled connection to a host that vanished without a reset could hang; `tcp_user_timeout` (3 s) and `statement_timeout` bound it to roughly the 5 s budget.
- **Readiness thread pool**: a hanging check keeps a worker for up to the connect timeout (2 s); with two workers and a 500 ms wait the probe still answers in time.
