---
spec_id: 002-keep-tasks-in-postgres-and-report-not
title: Keep tasks in Postgres and report not-ready and 503 when the database is unreachable
status: approved
priority: P1
shape: service-python
parent: ika100/demo-taskboard-gitops:001-persistent-tasks-and-web-task-list
---

# 002 — Keep tasks in Postgres and report not-ready and 503 when the database is unreachable

## Problem

The taskboard API keeps tasks in memory, so every restart, redeploy or new image pin in an environment wipes all tasks, and two API instances would each show a different list. The web app is still the starter page: people can't see or create tasks without calling the API by hand. Together this means the system can't be used for real work yet. This spec makes tasks survive restarts by keeping them in the system's Postgres database, and turns the web app into the place where people see and add tasks.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-list` in `ika100/demo-taskboard-gitops` for `demo-taskboard-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks were created through the task API, when the API is restarted or redeployed with a new image, then `GET /tasks` returns the same tasks, each with the same `id`, `title`, `due_date` and `created_at` as when it was created, oldest first.
- **AC-001.2** Given two running instances of the task API in the same environment, when a task is created through one instance, then `GET /tasks` on the other instance contains it.
- **AC-001.3** Given the database cannot be reached, when a client sends `POST /tasks` or `GET /tasks`, then the response is `503` with a JSON error body, no task is created, and the list is never answered with `[]` in place of the stored tasks.
- **AC-001.4** Given the database cannot be reached, when the API's readiness endpoint is called, then it does not answer `200`; once the database is reachable again it answers `200` without the API being restarted.
- **AC-001.5** Given tasks exist in one environment (for example dev), when the task list is read in another environment (for example staging), then it does not contain them: each environment has its own tasks.

### Contract

The task API is reached inside each environment's namespace at `http://demo-taskboard-api` (port 80, the Service; env var `API_URL` in the web app). Only the web app's server side calls it. JSON over HTTP, `Content-Type: application/json`, UTF-8. No authentication.

### `GET /tasks`

- `200`: a JSON array of every task, oldest first (creation order). Empty array `[]` only when the database holds no tasks.
- `503`: the database cannot be reached (body in Errors). Never `200 []` in that case.

### `POST /tasks`

Request body:

| field | type | rules |
|---|---|---|
| `title` | string, required | surrounding whitespace trimmed by the API; after trimming 1 to 200 characters |
| `due_date` | string `YYYY-MM-DD` or `null`, optional | a real calendar date, no time part; past dates accepted |

The web app sends `due_date: null` (or omits it) when the date field is empty, and the `<input type="date">` value (`YYYY-MM-DD`) otherwise.

- `201`: the created task (object below).
- `422`: validation failed, no task created (body in Errors).
- `503`: the database cannot be reached, no task created.

The API has no idempotency key: two requests create two tasks. Exactly-once from a double click (AC-001.15) is the web app's job (one in-flight request per form).

### Task object

```json
{"id": "3f0c…", "title": "Buy milk", "due_date": "2026-12-01", "created_at": "2026-11-04T10:15:30.123456Z"}
```

| field | type | notes |
|---|---|---|
| `id` | non-empty string | opaque; clients must not parse it |
| `title` | string | trimmed, 1 to 200 characters |
| `due_date` | string `YYYY-MM-DD` or `null` | exactly as stored, no time zone |
| `created_at` | string, ISO 8601 UTC with `Z` | set by the API; unchanged on every later read |

### `GET /ready` (probe, not called by the web app)

- `200` `{"status": "ready"}` when a trivial query (`SELECT 1`) against the database succeeds.
- `503` `{"status": "not ready"}` otherwise. Checked on every call, so it returns to `200` once the database is back, without a restart.
- `GET /health` stays `200` `{"status": "ok"}` regardless of the database.

### Errors

- `422` uses FastAPI's standard validation format: `{"detail": [{"loc": ["body", "<field>"], "msg": "<text>", "type": "<code>"}, ...]}`; the field name is the last element of `loc` (`title` or `due_date`).
- `503` body: `{"detail": "Task storage is unavailable."}`. The API logs the underlying database error; it never puts it in the response.
- Unexpected server failures answer `500` with `{"detail": "Internal Server Error"}`.
- **How the web app treats responses:**
  - `GET /tasks`: anything other than `200` with a JSON array (any 4xx/5xx, a body that is not an array, a network error, a timeout) shows "Tasks could not be loaded. Please try again later." in place of the list; the page itself answers `200`.
  - `POST /tasks`: `201` appends the returned task. `422` naming `title` shows "Enter a title." (it should not happen, the form checks first). Any other status, including `422` on `due_date`, `503`, `500`, an unlisted status, a network error or a timeout, shows "The task could not be saved. Please try again." and keeps the inputs; nothing is added to the list.
- Web app internal: when the server action / route handler fails it returns a typed result to the client (`{ok: true, task}` or `{ok: false, reason: "invalid-title" | "unavailable"}`), never throws to `error.tsx`.

### Timeouts

- **Web app to API, `GET /tasks`:** 5 s total (connect plus response). On timeout or connection refused: the load error message, no retry within the request; the next page load tries again.
- **Web app to API, `POST /tasks`:** 5 s total. On timeout: the save error message, inputs kept, **no automatic retry** (a retry could create a duplicate). The submit button is enabled again after the response or the timeout.
- **API to Postgres:** connect timeout 2 s, statement timeout 3 s per query, so the API answers `503` within about 4 s, inside the web app's 5 s. Connections come from a pool that drops broken connections and reconnects on the next request; no in-API retries.
- **`/ready` to Postgres:** at most 500 ms for the check (the kubelet probe timeout is 1 s); on timeout `/ready` answers `503`.
- When the API pod is down or not ready, the Service has no endpoints and the web app sees a connection error: same handling as a timeout.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Withdraw AC-001.11 of this repo's spec 001-create-and-list-tasks and its non-goals
"persistence beyond the process lifetime" and "sharing tasks across replicas"
(superseded by system spec 001-persistent-tasks-and-web-task-list).
Configuration comes only from the injected DATABASE_URL (PG* are also set); no
other DB settings. Replace the in-memory TaskStore with a Postgres-backed store;
the request/response format and validation of AC-001.1 to AC-001.10 of spec
001-create-and-list-tasks stay unchanged. The schema (one `tasks` table) is created
by the service itself, idempotently, under a Postgres advisory lock so two replicas
starting together do not race; the service must start and serve /health even when
the database is down at startup, and create the schema on the first successful
connection (no restart needed, AC-001.4). Order by created_at then a monotonic
sequence column so tasks created in the same instant keep creation order.
Tests run against a real Postgres (testcontainers or a devbox service), plus a
test that stops it to cover 503 and not-ready. Smoke: keep AC-001.8's smoke out
(the list is no longer empty after a deploy); AC-001.1 of the old spec stays the smoke.

## Stories

As an API client (the web app's server side), I want tasks I created to still be there after the API restarts or is redeployed, so that people never lose their tasks.

As an API client, I want every instance of the API in an environment to return the same task list, so that the list does not depend on which instance answers.

As an API client, I want a clear `503` when task storage is unavailable, so that I can show an error instead of an empty list or a lost task.

As an operator, I want the API to report not-ready while the database is unreachable and to recover on its own when it is back, so that traffic only reaches instances that can serve it and no restart is needed.

## Acceptance criteria

- **AC-002.1** Given tasks were created through `POST /tasks`, when the service is restarted (or replaced by an instance of a new image) against the same database, then `GET /tasks` returns `200` with the same tasks, each with the same `id`, `title`, `due_date` and `created_at` as returned at creation, oldest first. (system AC-001.1)
- **AC-002.2** Given several tasks are created one after another in quick succession (including ones whose `created_at` values are identical), when `GET /tasks` is sent, then they are listed in the order they were created, oldest first, on every read. (system AC-001.1)
- **AC-002.3** Given the database is reachable, when the create and list requests of spec 001-create-and-list-tasks AC-001.1 to AC-001.7, AC-001.9 and AC-001.10 are sent, then the responses (status codes, body fields, `422` validation errors naming `title` or `due_date`, trimming, limits) are exactly as specified there. (system AC-001.1)
- **AC-002.4** Given the database is reachable and holds no tasks, when `GET /tasks` is sent, then the response is `200` with the JSON body `[]`. (system AC-001.3)
- **AC-002.5** Given two running instances of the service using the same database, when a task is created through one instance, then `GET /tasks` on the other instance contains it with the same `id`, `title`, `due_date` and `created_at`. (system AC-001.2)
- **AC-002.6** Given two instances of the service start at the same time against a database that has never been used by the service, when both have started, then both answer `GET /ready` with `200` and `POST /tasks` and `GET /tasks` succeed on both without an error. (system AC-001.2)
- **AC-002.7** Given two instances of the service configured with different databases (as in two environments), when a task is created through the first, then `GET /tasks` on the second does not contain it. (system AC-001.5)
- **AC-002.8** Given the database cannot be reached, when a client sends `POST /tasks` with a valid body, then the response is `503` with the JSON body `{"detail": "Task storage is unavailable."}` within 5 seconds, and once the database is reachable again `GET /tasks` does not contain that task. (system AC-001.3)
- **AC-002.9** Given tasks are stored and the database then cannot be reached, when a client sends `GET /tasks`, then the response is `503` with the JSON body `{"detail": "Task storage is unavailable."}` within 5 seconds, never `200` with `[]`. (system AC-001.3)
- **AC-002.10** Given the database cannot be reached, when any `503` is returned by `POST /tasks` or `GET /tasks`, then the response body contains only the `detail` text above and no database error text, host name or credentials. (system AC-001.3)
- **AC-002.11** Given the database is reachable, when `GET /ready` is sent, then the response is `200` with `{"status": "ready"}`. (system AC-001.4) (smoke)
- **AC-002.12** Given the database cannot be reached, when `GET /ready` is sent, then the response is `503` with `{"status": "not ready"}` within 1 second, and `GET /health` still answers `200` with `{"status": "ok"}`. (system AC-001.4)
- **AC-002.13** Given the service was serving and the database became unreachable, when the database is reachable again, then without restarting the service `GET /ready` answers `200` and `POST /tasks` and `GET /tasks` succeed, with the tasks stored before the outage still listed. (system AC-001.4)
- **AC-002.14** Given the database cannot be reached when the service starts, when the service is started, then it starts and answers `GET /health` with `200` and `GET /ready` with `503`; once the database becomes reachable, without restarting the service, `GET /ready` answers `200` and `POST /tasks` followed by `GET /tasks` returns the created task. (system AC-001.4)

## Non-goals

- Database settings other than the injected `DATABASE_URL` (pool size, timeouts or a host configured separately).
- Retrying failed database calls inside the API; a failed call answers `503` and the client decides.
- An idempotency key or duplicate detection on `POST /tasks`; two requests create two tasks.
- Schema versioning or migration tooling beyond creating the one tasks table; carrying over tasks held in memory by earlier versions.
- Reading a single task, updating, completing or deleting tasks; filtering, search and pagination of the list.
- Users, authentication and per-user task lists.
- Backup and restore of the database (system concern).

## Open questions


## Changelog

- 2026-11-04 created
- 2026-11-04 approved
