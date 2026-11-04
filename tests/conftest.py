"""Shared pytest fixtures.

Database-backed tests (spec 002) use one real Postgres per session (testcontainers) and a
fresh database per test. Tests point an app at a database only through
`create_app(database_url=...)`; they never set DATABASE_URL in the environment.
"""

from __future__ import annotations

import socket
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from demo_taskboard_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the module-level (unconfigured) FastAPI application."""
    return TestClient(app)


class PgServer:
    def __init__(self, container: Any, base_url: str) -> None:
        self.container = container
        parts = urlsplit(base_url)
        self.host = parts.hostname or "127.0.0.1"
        self.port = parts.port or 5432
        self.user = parts.username or "test"
        self.password = parts.password or "test"

    def url_for(self, database: str, host: str | None = None, port: int | None = None) -> str:
        netloc = f"{self.user}:{self.password}@{host or self.host}:{port or self.port}"
        return urlunsplit(("postgresql", netloc, f"/{database}", "", ""))

    def create_database(self) -> str:
        name = f"t_{uuid.uuid4().hex}"
        result = self.container.exec(
            ["psql", "-U", self.user, "-d", "postgres", "-c", f"CREATE DATABASE {name}"]
        )
        assert result.exit_code == 0, result.output
        return name


@pytest.fixture(scope="session")
def pg_server() -> Iterator[PgServer]:
    """One Postgres container for the whole test session."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        yield PgServer(container, container.get_connection_url())


@pytest.fixture()
def db_url(pg_server: PgServer) -> str:
    """URL of a brand-new, empty database on the session Postgres."""
    return pg_server.url_for(pg_server.create_database())


@pytest.fixture()
def make_db_url(pg_server: PgServer) -> Callable[[], str]:
    """Factory for several independent fresh databases in one test."""
    return lambda: pg_server.url_for(pg_server.create_database())


class TcpProxy:
    """A TCP proxy that can be stopped (listener and open connections) and restarted."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self.target = (target_host, target_port)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self._listener: socket.socket | None = None
        self._conns: list[socket.socket] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(64)
        self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            if self._listener is not listener:
                client.close()
                return
            try:
                upstream = socket.create_connection(self.target, timeout=5)
            except OSError:
                client.close()
                continue
            with self._lock:
                self._conns += [client, upstream]
            threading.Thread(target=self._pipe, args=(client, upstream), daemon=True).start()
            threading.Thread(target=self._pipe, args=(upstream, client), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def stop(self) -> None:
        if self._listener is not None:
            listener, self._listener = self._listener, None
            try:
                # close() alone does not wake a blocked accept() on Linux
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        with self._lock:
            conns, self._conns = self._conns, []
        for s in conns:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()


class ProxiedDb:
    def __init__(self, proxy: TcpProxy, url: str) -> None:
        self.proxy = proxy
        self.url = url

    def down(self) -> None:
        self.proxy.stop()

    def up(self) -> None:
        self.proxy.start()


@pytest.fixture()
def proxied_db(pg_server: PgServer, db_url: str) -> Iterator[ProxiedDb]:
    """A fresh database reached through a proxy that tests can stop and restart (starts up)."""
    database = urlsplit(db_url).path.lstrip("/")
    proxy = TcpProxy(pg_server.host, pg_server.port)
    proxy.start()
    try:
        yield ProxiedDb(proxy, pg_server.url_for(database, "127.0.0.1", proxy.port))
    finally:
        proxy.stop()
