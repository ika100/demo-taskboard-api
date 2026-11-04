# Verification — 002 Keep tasks in Postgres and report not-ready and 503 when the database is unreachable

**Result:** pass
**Commit:** 73b93c2 · **Base:** b6eab8f · **Trace:** 14/14 criteria named by tests (AC-002.11 also has a smoke test)

Test run (phase 3): `devbox run ci` green, 68 passed / 4 skipped (smoke, no `SMOKE_BASE_URL`), coverage 96 %. The acceptance tests are unchanged since the red commit `2da78b6`: `git diff 2da78b6..HEAD -- tests` touches only `tests/test_db.py` (new unit tests) and `tests/test_task_store.py` (rewritten unit tests, as the plan's t4 says).

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_tasks_survive_restart` | `src/demo_taskboard_api/task_store.py:34-38`, `:57-65`; `src/demo_taskboard_api/main.py:89-90` | A new `create_app(url)` on the same database returns a list equal to the creation responses (id, title, due_date, created_at, order). `id` and `created_at` come from the database via `RETURNING`, so the values read back are the ones returned at creation. |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_creation_order_with_rapid_inserts` | `src/demo_taskboard_api/task_store.py:25,29,38` (`seq` identity, `ORDER BY created_at, seq`) | 30 quick inserts, the order is checked on 3 reads. Gap: over HTTP the test cannot force two equal `created_at` values, so the tie-break is shown by the code (`seq` as second sort key), not by a test. The behaviour is implemented as the design says. A store-level test that inserts equal timestamps would close the gap; this does not block the result. |
| AC-002.3 | met | `tests/test_tasks.py` (all tests tagged `AC-002.3`: `test_create_task_returns_201_body`, `test_create_task_with_due_date`, `test_invalid_title_rejected`, `test_title_length_limit`, `test_title_is_trimmed`, `test_invalid_due_date_rejected`, `test_past_due_date_accepted`, `test_list_in_creation_order`, `test_same_title_gets_distinct_ids`) | `src/demo_taskboard_api/tasks_api.py` (routes and schemas unchanged apart from the store type), `src/demo_taskboard_api/task_store.py:57-65` | The spec 001 tests now use the fresh-database `fresh` fixture (`tests/test_tasks.py:15-20`). Their assertions are unchanged from spec 001, apart from the withdrawn AC-001.11. |
| AC-002.4 | met | `tests/test_tasks_postgres.py::test_empty_database_lists_empty_array`, `tests/test_tasks.py::test_list_empty_on_fresh_database` | `src/demo_taskboard_api/task_store.py:62-65` | `200 []` on a brand-new database. |
| AC-002.5 | met | `tests/test_tasks_postgres.py::test_task_visible_on_other_instance` | `src/demo_taskboard_api/main.py:89-90` (one `Database` per instance, shared table) | Checked in both directions; the task objects are equal field for field. |
| AC-002.6 | met | `tests/test_tasks_postgres.py::test_two_instances_start_together_on_unused_database` | `src/demo_taskboard_api/db.py:67-75` (advisory xact lock + `IF NOT EXISTS` DDL), `src/demo_taskboard_api/task_store.py:23-32` | Two apps on a never-used database. A barrier makes both send their first call (`/ready`) at the same moment. The test expects `(200, 201, 200)` on both and 2 tasks in the list. |
| AC-002.7 | met | `tests/test_tasks_postgres.py::test_different_databases_do_not_share_tasks` | `src/demo_taskboard_api/main.py:77,89` | Two fresh databases; the second one lists `[]`. |
| AC-002.8 | met | `tests/test_tasks_postgres.py::test_post_while_database_down_is_503` | `src/demo_taskboard_api/db.py:82-88`, `src/demo_taskboard_api/main.py:55-62,87` | Proxy stopped: `503` with the exact body in under 5 s. After the proxy is back, the list does not contain "lost?". |
| AC-002.9 | met | `tests/test_tasks_postgres.py::test_get_while_database_down_is_503_not_empty_list` | `src/demo_taskboard_api/task_store.py:62-65` (no fallback to `[]`), `src/demo_taskboard_api/db.py:87-88` | A task is stored, then the database goes down: `503` with the exact body in under 5 s. |
| AC-002.10 | met | `tests/test_tasks_postgres.py::test_503_body_leaks_nothing`; unit `tests/test_db.py::test_closed_port_maps_to_storage_unavailable_without_leaking` | `src/demo_taskboard_api/main.py:62` (fixed body), `src/demo_taskboard_api/db.py:27-28,64-65,88` (no message on the exception, `repr` without the URL) | Checks GET and POST: the exact body, a JSON content type, and none of host, port, user/password (`test`), `psycopg` or `postgres` in the body. |
| AC-002.11 | met | `tests/test_tasks_postgres.py::test_ready_with_database_is_200`; smoke `tests/test_smoke_ac_002_11.py::test_smoke_ac_002_11_ready_with_database` | `src/demo_taskboard_api/main.py:38-42`, `src/demo_taskboard_api/db.py:90-106` | The smoke test is tagged `@pytest.mark.smoke`, reaches the service only through `smoke_base_url` and was skipped in CI (needs a deployment). |
| AC-002.12 | met | `tests/test_tasks_postgres.py::test_ready_503_fast_and_health_ok_when_database_down`, `tests/test_health.py::test_ready_without_database_is_not_ready` | `src/demo_taskboard_api/db.py:95-106` (`future.result(timeout=0.5)`), `src/demo_taskboard_api/main.py:33-35,40-42` | `503 {"status": "not ready"}` in under 1 s while `/health` stays `200 {"status": "ok"}`. |
| AC-002.13 | met | `tests/test_tasks_postgres.py::test_recovers_after_outage_without_restart` | `src/demo_taskboard_api/db.py:52` (`pool_pre_ping`), `:95-106` (checked on every call) | The same app instance is used throughout: `503` on `/ready` and `/tasks`, then `/ready` `200 ready`, POST `201`, and the list holds `[before, after]`. |
| AC-002.14 | met | `tests/test_tasks_postgres.py::test_starts_with_database_down_and_recovers` | `src/demo_taskboard_api/main.py:69-72` (lifespan does nothing at startup), `src/demo_taskboard_api/db.py:42-62` (no connection in the constructor), `:67-75` (lazy schema) | The proxy is stopped before `create_app`: `/health` `200`, `/ready` `503`. After the proxy is back, `/ready` `200` and POST then GET return the created task. |

## Non-goals

- Configuration beyond `DATABASE_URL`: only `DATABASE_URL` is read (`main.py:77`). Pool size and timeouts are constants (`db.py:15-19,50-61`). The `PG*` variables are not read. ✔
- In-API retries: none. `connection()` maps the error and raises (`db.py:87-88`). ✔
- Idempotency key or duplicate detection: none. ✔
- Migration tooling and carrying over in-memory tasks: only the idempotent `CREATE ... IF NOT EXISTS` (`task_store.py:23-32`). ✔
- Single-task read, update, delete, filter, pagination, auth, backup: none added. ✔

## Deviations from the plan

- `docs/specs/001-create-and-list-tasks/plan.md` changed but is in no task's `files`. The t2 coder removed the withdrawn AC-001.11 from its `covers` and refreshed `spec_hash` so `cplat spec check` stays green. Acceptable: a necessary result of t2.
- `tests/conftest.py`, `tests/test_tasks.py`, `tests/test_tasks_postgres.py`, `tests/test_smoke_ac_002_11.py`, `tests/test_smoke_tasks.py` and the `testcontainers` entry in `pyproject.toml`/`uv.lock` belong to the acceptance-test commit `2da78b6`, not to a task. Acceptable: that is the test-first phase, and t1 says to keep the entry.
- `docs/adr/001-postgres-access-with-sqlalchemy-core.md`, `design.md` and `plan.md` were added by the planning commits. Acceptable.
- All tasks t1 to t5 are `done: true`.

## Contract

The build matches `design.md` (status codes, 503 body `{"detail": "Task storage is unavailable."}`, `/ready` bodies, `/health` without a database call, JSON 500 handler at `main.py:65-66,88`, engine settings and constants, `TASKS_SCHEMA`, insert and select SQL). It differs in these points:

- `Database.connection()` uses `engine.connect()`, runs and commits the schema DDL in its own transaction, then opens `conn.begin()` for the body (`db.py:83-86`). The design and plan say "context manager over `engine.begin()`". Acceptable, and a small improvement: the DDL is committed before the body's transaction, so a failing body cannot roll back the schema while `_schema_ready` is already `True`. The advisory lock is still transaction-scoped and is released when the DDL commits (`db.py:71-74`).
- `tcp_user_timeout` is the literal `3000` (`db.py:60`), not a named constant. Cosmetic.
- `_ensure_schema` holds a per-instance `threading.Lock` while it runs DDL over the network. A concurrent `/ready` worker can wait behind it, but `is_ready` still answers within `READY_TIMEOUT_S` because it bounds the wait on the future (`db.py:99`). Acceptable.

## Open risk (from design.md, not a criterion)

The platform-owned `scripts/image-smoke.sh` runs the image without Postgres and `curl -f`s `/ready` and `/tasks`. After this change those answer `503`, so that script will fail. It is outside this repo's editable scope, so it has to be reported to the platform (`/issue:report`) before the image-smoke gate is relied on.
