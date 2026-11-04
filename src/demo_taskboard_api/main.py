"""FastAPI entry point for demo-taskboard-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import tasks_api
from .db import Database, StorageUnavailable
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .task_store import TASKS_SCHEMA, PostgresTaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    status: str


def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


def ready(request: Request) -> Response:
    """Readiness probe — 200 when the database answers, else 503."""
    if request.app.state.database.is_ready():
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not ready"}, status_code=503)


def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "demo-taskboard-api"}


def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def storage_unavailable_handler(request: Request, exc: Exception) -> Response:
    cause = exc.__cause__
    logger.warning(
        "task_storage_unavailable",
        error_type=type(cause).__name__,
        error=str(cause),
    )
    return JSONResponse({"detail": "Task storage is unavailable."}, status_code=503)


async def unhandled_handler(request: Request, exc: Exception) -> Response:
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    yield
    application.state.database.dispose()


def create_app(database_url: str | None = None) -> FastAPI:
    """Build an app instance with its own database handle (never connects at startup)."""
    url = database_url or os.environ.get("DATABASE_URL") or None
    if url is None:
        logger.warning("database_unconfigured")
    application = FastAPI(title="demo-taskboard-api", version="0.1.0", lifespan=lifespan)
    application.add_middleware(MetricsMiddleware)
    application.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    application.add_api_route("/ready", ready, methods=["GET"])
    application.add_api_route("/ping", ping, methods=["GET"])
    application.add_api_route("/metrics", metrics, methods=["GET"])
    application.include_router(tasks_api.router)
    application.add_exception_handler(StorageUnavailable, storage_unavailable_handler)
    application.add_exception_handler(Exception, unhandled_handler)
    application.state.database = Database(url, TASKS_SCHEMA)
    application.state.task_store = PostgresTaskStore(application.state.database)
    return application


app = create_app()
