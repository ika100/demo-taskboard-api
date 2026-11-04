# ADR-001: Postgres access with SQLAlchemy Core and psycopg 3, self-managed schema, real Postgres in tests

## Status

Accepted (spec 002-keep-tasks-in-postgres-and-report-not, 2026-11-04).

## Context

Spec 002 moves the task list from process memory into the system's Postgres database (CloudNativePG, injected as `DATABASE_URL` by the gitops repo). The service must:

- start and answer `/health` while the database is down, report `/ready` honestly on every call, and recover without a restart;
- fail fast (connect 2 s, statement 3 s) and answer `503` instead of hanging, with no retries inside the API;
- create its own schema idempotently when two replicas start at the same time;
- take no database configuration other than `DATABASE_URL`.

This is the first database access in the repo, so the choices below shape every later feature that stores data.

## Decision

1. **SQLAlchemy 2 Core (no ORM) on the psycopg 3 driver** (`sqlalchemy`, `psycopg[binary]`). Its `QueuePool` with `pool_pre_ping=True` opens connections on demand in the request thread, drops a broken connection at checkout and reconnects on the next request, with no background reconnect loop whose back-off could delay recovery. Plain SQL text statements, no ORM models.
2. **Timeouts are code constants, not configuration**: `connect_timeout=2`, `statement_timeout=3000` ms (libpq `options`), `tcp_user_timeout=3000` ms, pool checkout timeout 3 s. Only `DATABASE_URL` is read from the environment.
3. **One `Database` object per app instance** (`db.py`) owns the engine, maps connection-level driver errors to a single `StorageUnavailable` exception (answered as `503` by one exception handler), runs the readiness ping with a hard 500 ms budget, and ensures the schema lazily on the first successful connection.
4. **The schema is created by the service**: `CREATE TABLE IF NOT EXISTS` inside a transaction that first takes `pg_advisory_xact_lock(<fixed key>)`, so concurrent replicas serialize. No migration tool until a spec needs a schema change; that spec introduces one (Alembic) and records it in a new ADR.
5. **Tests run against a real Postgres** started by `testcontainers` (Docker); database outages are simulated with an in-test TCP proxy in front of it. No SQLite or mocks for storage behaviour.

## Consequences

**Positive:** recovery after an outage is deterministic (the next request reconnects); the 503/ready behaviour is testable end to end; adding a second table later reuses `Database` unchanged.

**Negative:** `devbox run test` needs a running Docker daemon (GitHub-hosted runners have one; a self-hosted `CI_RUNNER` must too). The ready check runs in a small thread pool so a hanging connect cannot hold the probe beyond 500 ms. A future schema change needs a migration tool, which this ADR deliberately postpones.
