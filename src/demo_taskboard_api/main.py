"""FastAPI entry point for demo-taskboard-api."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import tasks_api
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .task_store import TaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


def ready() -> HealthResponse:
    """Readiness probe — returns 200 when the service is ready to accept traffic."""
    return HealthResponse(status="ready")


def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "demo-taskboard-api"}


def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def create_app() -> FastAPI:
    """Build an app instance with its own empty task store."""
    application = FastAPI(title="demo-taskboard-api", version="0.1.0")
    application.add_middleware(MetricsMiddleware)
    application.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    application.add_api_route("/ready", ready, methods=["GET"], response_model=HealthResponse)
    application.add_api_route("/ping", ping, methods=["GET"])
    application.add_api_route("/metrics", metrics, methods=["GET"])
    application.include_router(tasks_api.router)
    application.state.task_store = TaskStore()
    return application


app = create_app()
