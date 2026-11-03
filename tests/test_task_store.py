from datetime import UTC, date

from demo_taskboard_api.task_store import TaskStore


def test_empty_on_creation() -> None:
    assert TaskStore().list() == []


def test_order_preserved() -> None:
    store = TaskStore()
    a = store.add("A", None)
    b = store.add("B", date(2030, 1, 2))
    assert store.list() == [a, b]
    assert b.due_date == date(2030, 1, 2)
    assert a.created_at.tzinfo is UTC


def test_equal_titles_get_distinct_ids() -> None:
    store = TaskStore()
    a = store.add("same", None)
    b = store.add("same", None)
    assert a.id != b.id
    assert len(store.list()) == 2


def test_returned_list_is_copy() -> None:
    store = TaskStore()
    store.add("A", None)
    store.list().clear()
    assert len(store.list()) == 1


def test_new_store_is_independent() -> None:
    store = TaskStore()
    store.add("A", None)
    assert TaskStore().list() == []
