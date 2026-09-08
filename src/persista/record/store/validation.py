r"""Provide validation helpers for
:class:`~persista.record.store.base.BaseRecordStore` implementations."""

from __future__ import annotations

__all__ = ["check_is_closed", "check_is_open"]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.record.store.base import BaseRecordStore


def check_is_open(store: BaseRecordStore) -> None:
    """Check that a record store is open, raising if it is not.

    Args:
        store: The :class:`~persista.record.store.base.BaseRecordStore`
            to check.

    Raises:
        RuntimeError: If ``store`` is closed.

    Example:
        ```pycon
        >>> from persista.record.store import InMemoryRecordStore
        >>> from persista.record.store.validation import check_is_open
        >>> store = InMemoryRecordStore()
        >>> with store:
        ...     check_is_open(store)
        ...

        ```
    """
    if store.closed:
        msg = (
            f"{type(store).__name__} is not open; call open()/aopen() or use it as a "
            "context manager."
        )
        raise RuntimeError(msg)


def check_is_closed(store: BaseRecordStore) -> None:
    """Check that a record store is closed, raising if it is not.

    Args:
        store: The :class:`~persista.record.store.base.BaseRecordStore`
            to check.

    Raises:
        RuntimeError: If ``store`` is open.

    Example:
        ```pycon
        >>> from persista.record.store import InMemoryRecordStore
        >>> from persista.record.store.validation import check_is_closed
        >>> store = InMemoryRecordStore()
        >>> check_is_closed(store)

        ```
    """
    if not store.closed:
        msg = f"{type(store).__name__} is not closed; call close()/aclose() first."
        raise RuntimeError(msg)
