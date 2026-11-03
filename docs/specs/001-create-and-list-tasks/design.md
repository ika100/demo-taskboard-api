# Design — 001 Create and list tasks

## Decisions

- **In-memory store owned by the app instance.** A `TaskStore` (append-only list guarded by a `threading.Lock`, because sync FastAPI handlers run in a thread pool) is created inside a new `create_app()` factory and kept on `app.state.task_store`. Handlers reach it through a `get_task_store(request)` dependency. A new app instance starts empty, which is exactly what a restart does (AC-001.8, AC-001.11), and gives tests a clean store without global reset hooks. `main.app = create_app()` stays the uvicorn entry point.
- **Flat modules, like the existing `metrics.py` / `tracing.py`:** API schemas, store and router are three modules. Schemas and store do not import each other (the router maps a `Task` to a `TaskResponse` with `TaskResponse.model_validate(task, from_attributes=True)`), so they are built in parallel.
- **Validation is done by Pydantic, errors use FastAPI's standard 422 body.** No custom error handler: the spec asks for "the standard validation error format".
- **`due_date` is validated explicitly**, not via Pydantic's `date` type in lax mode: lax `date` parsing also accepts Unix timestamps and datetime strings with a zero time, which AC-001.6 rejects. A before-validator requires a JSON string matching `^\d{4}-\d{2}-\d{2}$` and then `date.fromisoformat` (rejects `2026-13-01`, `2026-02-30`). Past dates are fine (AC-001.7).
- **`id` is a UUID4 string**; `created_at` is taken from `datetime.now(UTC)` when the store appends the task.

No ADR: everything here is local to this feature; persistence will be its own spec.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/demo_taskboard_api/task_schemas.py` | `TaskCreate` (request) and `TaskResponse` (response) Pydantic models, title trim/length rule, `due_date` rule, `created_at` serialization | new |
| `src/demo_taskboard_api/task_store.py` | `Task` record (frozen dataclass) and `TaskStore` (`add`, `list`) | new |
| `src/demo_taskboard_api/tasks_api.py` | `APIRouter` with `POST /tasks` and `GET /tasks`, `get_task_store` dependency, `Task` → `TaskResponse` mapping | new |
| `src/demo_taskboard_api/main.py` | `create_app()` factory: middleware, existing routes, task router, fresh `TaskStore` on `app.state`; `app = create_app()` | changed |

Public interfaces (signatures only):

```python
# task_store.py
@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: date | None
    created_at: datetime          # timezone-aware, UTC

class TaskStore:
    def add(self, title: str, due_date: date | None) -> Task: ...   # assigns uuid4 id + created_at, appends
    def list(self) -> list[Task]: ...                               # copy, creation order (oldest first)

# task_schemas.py
class TaskCreate(BaseModel):     # title: str (trimmed, 1..200 chars); due_date: date | None (see Contract)
class TaskResponse(BaseModel):   # id: str, title: str, due_date: date | None, created_at: datetime (serialized UTC with "Z")

# tasks_api.py
router: APIRouter
def get_task_store(request: Request) -> TaskStore: ...

# main.py
def create_app() -> FastAPI: ...
app: FastAPI
```

## Contract

### `POST /tasks`

Request body (`application/json`):

| Field | Type | Rules |
|---|---|---|
| `title` | string | required; not `null`; surrounding whitespace is trimmed (AC-001.5); after trimming 1..200 characters (AC-001.3, AC-001.4). Non-string values (numbers, booleans) are rejected. |
| `due_date` | string \| null | optional, default `null`; when present and not `null`, exactly `YYYY-MM-DD` and a real calendar date (AC-001.6); dates in the past are accepted (AC-001.7). |

Unknown fields are ignored.

`201 Created`, body (AC-001.1, AC-001.2):

```json
{
  "id": "6f1c1f5e-2a8e-4d4b-9a51-0d6f7c2b9e10",
  "title": "Buy milk",
  "due_date": null,
  "created_at": "2026-11-03T09:30:00.123456Z"
}
```

- `id`: non-empty string (UUID4), unique per task (AC-001.10).
- `title`: the trimmed title.
- `due_date`: `"YYYY-MM-DD"` or `null`, exactly as sent.
- `created_at`: ISO 8601 / RFC 3339 in UTC with the `Z` suffix. Tests should parse it (`datetime.fromisoformat`) and check the offset is zero rather than string-match the precision.

`422 Unprocessable Entity` on any invalid input, FastAPI's standard validation body; the last element of `loc` names the field (AC-001.3, AC-001.4, AC-001.6):

```json
{
  "detail": [
    {"type": "string_too_short", "loc": ["body", "title"], "msg": "String should have at least 1 character", "input": "   "}
  ]
}
```

Callers and tests may rely on `detail` being a non-empty list whose entries have `loc` ending in `"title"` or `"due_date"`; `type` and `msg` are informational and not part of the contract. A 422 never stores a task.

Malformed JSON or a non-object body also answers `422` in the same format (FastAPI default).

### `GET /tasks`

`200 OK`, body: JSON array of task objects in the same shape as the `POST` response, in creation order, oldest first (AC-001.9). Each element is identical to the body returned when that task was created. Empty store: `[]` (AC-001.8). No query parameters.

### Restart semantics

Each process (and each `create_app()` instance) starts with an empty list (AC-001.11). Tests simulate a restart by building a new `TestClient(create_app())` (import `from demo_taskboard_api.main import create_app`). The shared `client` fixture in `tests/conftest.py` uses the module-level `app`, whose store persists across tests, so acceptance tests that need a known list (AC-001.3, AC-001.4, AC-001.6, AC-001.8 to AC-001.11) should use a fresh `create_app()` instance per test.

## Data

In-memory only: a Python list of `Task` records per app instance. No database, no migration, no new environment variables.

## Observability

`POST /tasks` logs one structlog event `task_created` with `task_id` and `has_due_date` (no title, it is user content). Request metrics come from the existing middleware under route `/tasks`.

## Risks

- Unbounded memory growth: accepted by the spec (non-goal: no cap).
- With several replicas each pod has its own list (non-goal); no gitops change is required by this spec.
