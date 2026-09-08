from __future__ import annotations

import pytest

from persista.record.store import InMemoryRecordStore
from persista.record.store.validation import check_is_closed, check_is_open

##########################################
#     Tests for check_is_open             #
##########################################


def test_check_is_open_does_not_raise_when_open() -> None:
    store = InMemoryRecordStore()
    with store:
        check_is_open(store)


def test_check_is_open_raises_when_closed() -> None:
    store = InMemoryRecordStore()
    with pytest.raises(RuntimeError, match="is not open"):
        check_is_open(store)


def test_check_is_open_raises_after_close() -> None:
    store = InMemoryRecordStore()
    store.open()
    store.close()
    with pytest.raises(RuntimeError, match="is not open"):
        check_is_open(store)


##########################################
#     Tests for check_is_closed           #
##########################################


def test_check_is_closed_does_not_raise_when_closed() -> None:
    store = InMemoryRecordStore()
    check_is_closed(store)


def test_check_is_closed_raises_when_open() -> None:
    store = InMemoryRecordStore()
    with store, pytest.raises(RuntimeError, match="is not closed"):
        check_is_closed(store)


def test_check_is_closed_does_not_raise_after_close() -> None:
    store = InMemoryRecordStore()
    store.open()
    store.close()
    check_is_closed(store)
