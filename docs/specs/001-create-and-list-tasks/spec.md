---
spec_id: 001-create-and-list-tasks
title: Create and list tasks
status: building
priority: P1
shape: service-python
---

# 001 — Create and list tasks

## Problem

The Task API has no tasks yet: it answers health, readiness and ping, but a client can't record anything to do or read it back. This is the first feature that makes the service useful. Clients need to create a task with a title and, if they want, a due date, and then see every task created so far. Tasks are kept in memory for now, so a restart deliberately starts empty and the feature ships without a database.

## Stories

As an API client, I want to create a task with a title and an optional due date, so that I can record something to do and when it is due.

As an API client, I want to list all tasks, so that I can see everything recorded so far and show it to my users.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a client sends `POST /tasks` with `{"title": "Buy milk"}`, then the response is `201` with a JSON body containing a non-empty string `id`, `"title": "Buy milk"`, `"due_date": null` and a `created_at` timestamp in ISO 8601 UTC. (smoke)
- **AC-001.2** Given the service is running, when a client sends `POST /tasks` with `{"title": "File taxes", "due_date": "2026-12-01"}`, then the response is `201` and the body contains `"due_date": "2026-12-01"`.
- **AC-001.3** Given a create request whose `title` is missing, `null`, an empty string, or only whitespace, when it is sent, then the response is `422` with an error that names the field `title`, and no task is created (a following `GET /tasks` does not contain it).
- **AC-001.4** Given a create request whose `title` is longer than 200 characters after surrounding whitespace is trimmed, when it is sent, then the response is `422` with an error that names the field `title`, and no task is created. A title of exactly 200 characters is accepted.
- **AC-001.5** Given a create request with `"title": "  Buy milk  "`, when it is sent, then the stored and returned title is `"Buy milk"` (surrounding whitespace removed).
- **AC-001.6** Given a create request whose `due_date` is not a calendar date in `YYYY-MM-DD` form (for example `"tomorrow"`, `"2026-13-01"`, `"2026-02-30"` or `"2026-12-01T10:00:00Z"`), when it is sent, then the response is `422` with an error that names the field `due_date`, and no task is created.
- **AC-001.7** Given a create request with a `due_date` before today, when it is sent, then the task is created (`201`) with that due date.
- **AC-001.8** Given no tasks have been created since the service started, when a client sends `GET /tasks`, then the response is `200` with the JSON body `[]`. (smoke)
- **AC-001.9** Given tasks "A" and then "B" were created, when a client sends `GET /tasks`, then the response is `200` with a JSON array of exactly those two tasks in creation order (oldest first), each with the same `id`, `title`, `due_date` and `created_at` returned when it was created.
- **AC-001.10** Given two create requests with the same title, when both are sent, then both succeed with different `id` values and both appear in `GET /tasks`.
- **AC-001.11** Given tasks were created, when the service restarts, then `GET /tasks` returns `[]`.

## Non-goals

- Persistence beyond the process lifetime (database, file storage); tasks are lost on restart by design.
- Reading a single task by id, updating, completing or deleting tasks.
- Filtering, sorting options, search and pagination of the list.
- Users, authentication and per-user task lists; every client sees every task.
- Sharing tasks across multiple replicas; each instance has its own list.
- Fields other than title and due date (description, priority, status, tags).
- Time-of-day or time zone on the due date.
- A cap on the number of tasks kept in memory.

## Open questions

- ~~Confirm: the resource path is `/tasks`?~~ Answered: yes, `POST /tasks` creates and `GET /tasks` lists; see AC-001.1–AC-001.11.
- ~~Confirm: the maximum title length is 200 characters?~~ Answered: 200 characters; see AC-001.4.
- ~~Confirm: is surrounding whitespace trimmed and a whitespace-only title rejected?~~ Answered: yes; see AC-001.3, AC-001.5.
- ~~Confirm: is the due date a date only (`YYYY-MM-DD`)?~~ Answered: yes, no time or time zone; see AC-001.6 and Non-goals.
- ~~Should a due date in the past be accepted?~~ Answered: yes, without a warning; see AC-001.7.
- ~~Confirm: is the list ordered by creation time, oldest first?~~ Answered: yes; see AC-001.9.
- ~~Should the number of tasks kept in memory be capped?~~ Answered: no cap in this spec; see Non-goals.
- ~~Confirm: do invalid requests answer `422` in the standard validation error format?~~ Answered: yes; see AC-001.3, AC-001.4, AC-001.6.

## Changelog

- 2026-11-03 created
- 2026-11-03 amended: all 8 open questions answered and struck through. The answers match the suggested defaults already written into AC-001.1–AC-001.11, so no criterion changed. Added the non-goal "no cap on the number of tasks kept in memory".
- 2026-11-03 approved
- 2026-11-03 building
