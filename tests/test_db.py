"""Unit tests for the Database module (no Docker)."""

from __future__ import annotations

import socket
import time

import pytest

from demo_taskboard_api.db import Database, StorageUnavailable, normalize_database_url


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@h:5432/d",
        "postgresql://u:p@h:5432/d",
        "postgresql+psycopg://u:p@h:5432/d",
    ],
)
def test_normalize_accepted_schemes(url: str) -> None:
    assert normalize_database_url(url) == "postgresql+psycopg://u:p@h:5432/d"


def test_normalize_rejects_other_schemes() -> None:
    with pytest.raises(ValueError):
        normalize_database_url("mysql://u:p@h/d")


def test_unconfigured_is_unavailable_and_not_ready() -> None:
    db = Database(None, ())
    with pytest.raises(StorageUnavailable):
        with db.connection():
            pass
    assert db.is_ready() is False
    db.dispose()


def test_closed_port_maps_to_storage_unavailable_without_leaking() -> None:
    creds = "someuser:s3cretpw"  # pragma: allowlist secret
    url = f"postgresql://{creds}@127.0.0.1:{_closed_port()}/db"
    db = Database(url, ("SELECT 1",))
    start = time.monotonic()
    with pytest.raises(StorageUnavailable) as info:
        with db.connection():
            pass
    assert time.monotonic() - start < 1
    assert "s3cretpw" not in str(info.value)
    assert "127.0.0.1" not in str(info.value)
    assert "s3cretpw" not in repr(db)

    start = time.monotonic()
    assert db.is_ready() is False
    assert time.monotonic() - start < 1
    db.dispose()
