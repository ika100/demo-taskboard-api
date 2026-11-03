"""HTTP endpoints for creating and listing tasks."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from .task_schemas import TaskCreate, TaskResponse
from .task_store import TaskStore

router = APIRouter(tags=["tasks"])
logger = structlog.get_logger(__name__)


def get_task_store(request: Request) -> TaskStore:
    """Return the task store owned by the running app instance."""
    store: TaskStore = request.app.state.task_store
    return store


@router.post("/tasks", status_code=201, response_model=TaskResponse)
def create_task(body: TaskCreate, request: Request) -> TaskResponse:
    """Create a task."""
    task = get_task_store(request).add(body.title, body.due_date)
    logger.info("task_created", task_id=task.id, has_due_date=task.due_date is not None)
    return TaskResponse.model_validate(task, from_attributes=True)


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(request: Request) -> list[TaskResponse]:
    """List tasks, oldest first."""
    return [
        TaskResponse.model_validate(t, from_attributes=True) for t in get_task_store(request).list()
    ]
