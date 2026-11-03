# Verification — 001 Create and list tasks

**Result:** pass
**Commit:** 137826b · **Base:** f91eb0a · **Trace:** 11/11 criteria named by tests (smoke: AC-001.1, AC-001.8)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_returns_201_body`, smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/demo_taskboard_api/tasks_api.py:21-26`, `src/demo_taskboard_api/task_store.py:26-35`, `src/demo_taskboard_api/task_schemas.py:45-49` | Asserts 201, non-empty string `id`, title, `due_date` null, `created_at` parses with zero UTC offset. Serializer emits `Z` suffix. |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_with_due_date` | `src/demo_taskboard_api/task_schemas.py:25-34` | Asserts 201 and `"due_date": "2026-12-01"`. |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_rejected[4 cases]` | `src/demo_taskboard_api/task_schemas.py:20-24` | All four cases (missing, `null`, `""`, whitespace) parametrized; asserts 422, `loc[-1] == "title"`, and `GET /tasks == []`. `Field(strict=True)` rejects null/non-strings; `strip_whitespace` runs before `min_length=1`. |
| AC-001.4 | met | `tests/test_tasks.py::test_title_length_limit` | `src/demo_taskboard_api/task_schemas.py:22` | 201 chars and padded 201 chars rejected with 422 (first names `title`), list stays empty; exactly 200 and padded 200 (length counted after trim) accepted with 201. |
| AC-001.5 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/demo_taskboard_api/task_schemas.py:22` | Checks both the returned and the stored (listed) title equal `"Buy milk"`. |
| AC-001.6 | met | `tests/test_tasks.py::test_invalid_due_date_rejected[4 cases]` | `src/demo_taskboard_api/task_schemas.py:16,27-34` | All four spec examples parametrized; asserts 422, `loc[-1] == "due_date"`, list empty. Regex blocks `tomorrow` and the datetime string; `date.fromisoformat` raises `ValueError` for `2026-13-01`/`2026-02-30`, which Pydantic reports under `due_date`. Non-strings (e.g. timestamps) also rejected at line 32. |
| AC-001.7 | met | `tests/test_tasks.py::test_past_due_date_accepted` | `src/demo_taskboard_api/task_schemas.py:27-34` | `2000-01-01` returns 201 with the date echoed; no comparison against today in the code. |
| AC-001.8 | met | `tests/test_tasks.py::test_list_empty_on_fresh_app`, smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_8_list_tasks` | `src/demo_taskboard_api/tasks_api.py:29-34`, `src/demo_taskboard_api/main.py:56` | Acceptance test asserts 200 and `[]` on a fresh app. The smoke test only asserts 200 and a JSON list, because a shared deployed environment cannot guarantee emptiness; acceptable given the smoke rules (never touch others' data). |
| AC-001.9 | met | `tests/test_tasks.py::test_list_in_creation_order` | `src/demo_taskboard_api/task_store.py:34,37-39` | Asserts `GET /tasks == [a, b]`, i.e. exactly two tasks, oldest first, with identical `id`/`title`/`due_date`/`created_at` as the create responses. |
| AC-001.10 | met | `tests/test_tasks.py::test_same_title_gets_distinct_ids` | `src/demo_taskboard_api/task_store.py:29` | Both 201, ids differ, list length 2. uuid4 per task, no dedup. |
| AC-001.11 | met | `tests/test_tasks.py::test_restart_empties_list` | `src/demo_taskboard_api/main.py:47-60` | Restart simulated by a new `create_app()` instance as the design specifies; each instance gets a fresh `TaskStore()` (main.py:56), no module-level store. |

## Acceptance tests integrity

`git diff 41422f3..HEAD -- tests/test_tasks.py tests/test_smoke_tasks.py` shows only the ruff `timezone.utc` -> `UTC` change and one reflowed decorator (commit 17dfd67, accepted by the user). No assertion was weakened, removed or skipped.

## Non-goals

No persistence, no get-by-id/update/delete routes, no filtering/sorting/pagination, no auth, no extra task fields, no time-of-day on `due_date`, no cap on stored tasks. `tasks_api.py` exposes only `POST /tasks` and `GET /tasks`. ✔

## Deviations from the plan

- `tests/test_tasks.py` and `tests/test_smoke_tasks.py` are in no task's `files`: they are the red-first acceptance tests (commit 41422f3), which the process writes before the tasks. Acceptable.
- `src/demo_taskboard_api/task_schemas.py:47-48` treats a naive `created_at` as UTC; not in the plan, defensive only (the store always produces aware UTC datetimes). Acceptable.
- All tasks t1, t2, t3 have `done: true`. ✔

## Contract

Matches `design.md`: `POST /tasks` -> 201 with `id`/`title`/`due_date`/`created_at` (UTC, `Z`), FastAPI default 422 with `loc` ending in the field, unknown fields ignored (Pydantic default); `GET /tasks` -> 200 array in creation order; `create_app()` factory with per-instance `TaskStore` on `app.state.task_store`, reached via `get_task_store(request)`; `task_created` log event with `task_id` and `has_due_date` only (`tasks_api.py:25`). Schemas and store do not import each other. Minor: `get_task_store` is called directly rather than wired as a FastAPI `Depends`; behaviour and signature match the design, so this is acceptable. ✔
