---
spec_id: 001-create-and-list-tasks
shape: service-python
spec_hash: 12687e2b5a75
summary: In-memory POST /tasks and GET /tasks with validated title and optional due date
tasks:
  - id: t1
    title: Add task request/response schemas with title and due_date validation
    files: [src/demo_taskboard_api/task_schemas.py, tests/test_task_schemas.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add in-memory TaskStore
    files: [src/demo_taskboard_api/task_store.py, tests/test_task_store.py]
    covers: [AC-001.8, AC-001.9, AC-001.10, AC-001.11]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Expose POST/GET /tasks and add the create_app factory
    files: [src/demo_taskboard_api/tasks_api.py, src/demo_taskboard_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11]
    parallel_safe: false
    depends_on: [t1, t2]
    done: true
---

# Plan — 001 Create and list tasks

Design and contract: [design.md](design.md). Levels: t1, t2 (parallel) → t3.

## t1 — Add task request/response schemas with title and due_date validation

**Files:** src/demo_taskboard_api/task_schemas.py, tests/test_task_schemas.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Pydantic models that turn a create request into a validated title and due date, and serialize a task exactly as the contract in design.md says. No import of `task_store`.

**Implementation notes:**
- `TaskCreate.title`: `Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]`, required, no default; strict string (reject numbers/booleans: `Field(strict=True)` or `StrictStr` base). Length is checked after trimming (AC-001.4: 200 accepted, 201 rejected).
- `TaskCreate.due_date: date | None = None` with a `mode="before"` validator: `None` passes; otherwise require `str` matching `^\d{4}-\d{2}-\d{2}$`, then `date.fromisoformat`; raise `ValueError` otherwise so the 422 `loc` ends in `due_date`. No check against today (AC-001.7).
- `TaskResponse`: `id: str`, `title: str`, `due_date: date | None`, `created_at: datetime`; `model_config = ConfigDict(from_attributes=True)`; a `field_serializer` for `created_at` that emits UTC ISO 8601 with a `Z` suffix (`astimezone(UTC)`, `isoformat()` with `+00:00` replaced by `Z`). `due_date` serializes as `YYYY-MM-DD` (Pydantic default).
- Unknown request fields are ignored (Pydantic default `extra="ignore"`).
- Unit tests in `tests/test_task_schemas.py`: each title and due_date case from the spec, plus the `created_at` format.

**Done when:** `tests/test_task_schemas.py` passes and `devbox run quality` is clean. The HTTP acceptance tests pass only after t3.

## t2 — Add in-memory TaskStore

**Files:** src/demo_taskboard_api/task_store.py, tests/test_task_store.py
**Covers:** AC-001.8, AC-001.9, AC-001.10, AC-001.11
**Goal:** a thread-safe, append-only, per-instance store of `Task` records in creation order.

**Implementation notes:**
- `Task`: frozen dataclass `id: str`, `title: str`, `due_date: date | None`, `created_at: datetime` (aware, UTC).
- `TaskStore.__init__`: empty list and a `threading.Lock`.
- `add(title, due_date) -> Task`: under the lock, build `Task(id=str(uuid4()), created_at=datetime.now(UTC), ...)`, append, return it. No de-duplication by title (AC-001.10).
- `list() -> list[Task]`: under the lock, return a copy of the list (oldest first).
- No module-level instance: a new `TaskStore()` is empty (AC-001.8, AC-001.11).
- Unit tests in `tests/test_task_store.py`: empty on creation, order preserved, distinct ids for equal titles, returned list is a copy.

**Done when:** `tests/test_task_store.py` passes and `devbox run quality` is clean.

## t3 — Expose POST/GET /tasks and add the create_app factory

**Files:** src/demo_taskboard_api/tasks_api.py, src/demo_taskboard_api/main.py
**Covers:** AC-001.1 to AC-001.11
**Goal:** wire schemas and store into HTTP endpoints, and make each app instance own a fresh store so a restart (or a new `create_app()`) starts empty.

**Implementation notes:**
- `tasks_api.py`: `router = APIRouter(tags=["tasks"])`; `get_task_store(request: Request) -> TaskStore` returns `request.app.state.task_store`.
- `POST /tasks` (sync `def`, `status_code=201`, `response_model=TaskResponse`): `store.add(body.title, body.due_date)`, log `task_created` via structlog with `task_id` and `has_due_date`, return `TaskResponse.model_validate(task, from_attributes=True)`.
- `GET /tasks` (`response_model=list[TaskResponse]`): map `store.list()` the same way.
- `main.py`: keep `configure_logging` / tracing at module level; move app construction into `create_app() -> FastAPI` (FastAPI instance, `MetricsMiddleware`, `/health`, `/ready`, `/ping`, `/metrics` routes, `include_router(tasks_api.router)`, `app.state.task_store = TaskStore()`); then `app = create_app()`. Existing route handlers can stay module-level functions registered inside the factory (`app.add_api_route` or a router) so `tests/test_health.py`, `tests/test_metrics.py` keep passing unchanged.
- Validation errors keep FastAPI's default 422 handler; no custom handler.

**Done when:** every acceptance test for AC-001.1 to AC-001.11 passes, the existing health/metrics/tracing tests still pass, and `devbox run ci` is green (coverage gate included).
