"""Smoke test for AC-002.11: reaches the service only via its URL."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.smoke
def test_smoke_ac_002_11_ready_with_database(smoke_base_url: str) -> None:  # AC-002.11
    r = httpx.get(smoke_base_url + "/ready", timeout=10)
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
