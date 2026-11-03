"""Request/response schemas for tasks."""

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskCreate(BaseModel):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        Field(strict=True),
    ]
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, value: Any) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise ValueError("due_date must be a date in YYYY-MM-DD form")
        return date.fromisoformat(value)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    due_date: date | None
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
