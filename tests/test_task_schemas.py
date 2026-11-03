"""Unit tests for task schemas."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from demo_taskboard_api.task_schemas import TaskCreate, TaskResponse


def _field(exc: ValidationError) -> str:
    return str(exc.errors()[0]["loc"][-1])


@pytest.mark.parametrize("title", [None, "", "   ", 5, True])
def test_bad_title(title: object) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({"title": title})
    assert _field(ei.value) == "title"


def test_missing_title() -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({})
    assert _field(ei.value) == "title"


def test_title_length_limits() -> None:
    assert len(TaskCreate(title="a" * 200).title) == 200
    assert len(TaskCreate(title="  " + "a" * 200 + "  ").title) == 200
    with pytest.raises(ValidationError) as ei:
        TaskCreate(title="a" * 201)
    assert _field(ei.value) == "title"


def test_title_trimmed() -> None:
    assert TaskCreate(title="  Buy milk  ").title == "Buy milk"


def test_due_date_valid_and_default() -> None:
    assert TaskCreate(title="x").due_date is None
    assert TaskCreate.model_validate({"title": "x", "due_date": None}).due_date is None
    got = TaskCreate.model_validate({"title": "x", "due_date": "2026-12-01"})
    assert got.due_date == date(2026, 12, 1)


def test_due_date_past_accepted() -> None:
    got = TaskCreate.model_validate({"title": "x", "due_date": "2000-01-01"})
    assert got.due_date == date(2000, 1, 1)


@pytest.mark.parametrize(
    "value",
    ["tomorrow", "2026-13-01", "2026-02-30", "2026-12-01T10:00:00Z", "", 20261201, True],
)
def test_bad_due_date(value: object) -> None:
    with pytest.raises(ValidationError) as ei:
        TaskCreate.model_validate({"title": "x", "due_date": value})
    assert _field(ei.value) == "due_date"


def test_unknown_fields_ignored() -> None:
    assert TaskCreate.model_validate({"title": "x", "foo": 1}).title == "x"


def test_response_serialization() -> None:
    created = datetime(2026, 11, 3, 9, 30, 0, 123456, tzinfo=UTC)
    out = TaskResponse(id="abc", title="t", due_date=date(2026, 12, 1), created_at=created)
    assert out.model_dump(mode="json") == {
        "id": "abc",
        "title": "t",
        "due_date": "2026-12-01",
        "created_at": "2026-11-03T09:30:00.123456Z",
    }


def test_response_converts_to_utc() -> None:
    created = datetime(2026, 11, 3, 10, 30, tzinfo=timezone(timedelta(hours=1)))
    out = TaskResponse(id="a", title="t", due_date=None, created_at=created)
    dumped = out.model_dump(mode="json")
    assert dumped["created_at"] == "2026-11-03T09:30:00Z"
    assert dumped["due_date"] is None
