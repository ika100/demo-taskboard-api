"""Postgres access: engine, error mapping, readiness ping and lazy schema bootstrap."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager

import structlog
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy import exc as sa_exc

CONNECT_TIMEOUT_S = 2
STATEMENT_TIMEOUT_MS = 3000
POOL_TIMEOUT_S = 3
READY_TIMEOUT_S = 0.5
SCHEMA_LOCK_KEY = 2002001

logger = structlog.get_logger(__name__)

_DRIVER_PREFIX = "postgresql+psycopg://"
_ACCEPTED_PREFIXES = ("postgres://", "postgresql://", "postgresql+psycopg://")


class StorageUnavailable(Exception):  # noqa: N818 - name fixed by the design contract
    """The database cannot be reached; the original error is the __cause__."""


def normalize_database_url(url: str) -> str:
    """Map the accepted schemes to the psycopg 3 SQLAlchemy dialect."""
    for prefix in _ACCEPTED_PREFIXES:
        if url.startswith(prefix):
            return _DRIVER_PREFIX + url[len(prefix) :]
    raise ValueError("unsupported database URL scheme")


class Database:
    """One engine per app instance; never connects on construction."""

    def __init__(self, url: str | None, schema: Sequence[str]) -> None:
        self._schema = tuple(schema)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._last_ready: bool | None = None
        self._engine: Engine | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db-ready")
        if url is not None:
            self._engine = create_engine(
                normalize_database_url(url),
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=5,
                pool_timeout=POOL_TIMEOUT_S,
                pool_recycle=1800,
                connect_args={
                    "connect_timeout": CONNECT_TIMEOUT_S,
                    "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
                    "tcp_user_timeout": 3000,
                },
            )

    def __repr__(self) -> str:
        return f"Database(configured={self._engine is not None})"

    def _ensure_schema(self, conn: Connection) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY})
            for statement in self._schema:
                conn.execute(text(statement))
            conn.commit()
            self._schema_ready = True

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Yield a connection in a transaction; map connectivity errors to StorageUnavailable."""
        if self._engine is None:
            raise StorageUnavailable()
        try:
            with self._engine.connect() as conn:
                self._ensure_schema(conn)
                with conn.begin():
                    yield conn
        except (sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.TimeoutError) as exc:
            raise StorageUnavailable() from exc

    def _ping(self) -> None:
        with self.connection() as conn:
            conn.execute(text("SET LOCAL statement_timeout = '500ms'"))
            conn.execute(text("SELECT 1"))

    def is_ready(self) -> bool:
        if self._engine is None:
            return self._record(False)
        try:
            self._executor.submit(self._ping).result(timeout=READY_TIMEOUT_S)
            ready = True
        except (FutureTimeoutError, StorageUnavailable):
            ready = False
        except Exception:
            logger.exception("readiness_check_failed")
            ready = False
        return self._record(ready)

    def _record(self, ready: bool) -> bool:
        if ready != self._last_ready:
            self._last_ready = ready
            log = logger.info if ready else logger.warning
            log("readiness_changed", ready=ready)
        return ready

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._executor.shutdown(wait=False)
