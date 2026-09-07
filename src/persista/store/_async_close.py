r"""Provide a shared helper for closing a lazily-created async connection
from a store's synchronous ``close()`` method.

Several backends (SQLite, Redis, Postgres) eagerly open a sync
connection but only create their async connection lazily, on first
``a``-prefixed call. Closing such a store synchronously therefore has to
also tear down that async connection, which is only safe to do with
``asyncio.run`` when no event loop is currently running; this module
centralizes that check-and-close logic so it isn't re-implemented (and
potentially left to drift) in each backend.
"""

from __future__ import annotations

__all__ = ["close_async_connection_from_sync"]

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger: logging.Logger = logging.getLogger(__name__)


class _SupportsAsyncClose(Protocol):
    def close(self) -> Coroutine[Any, Any, Any]: ...  # pragma: no cover


def close_async_connection_from_sync(
    aconn: _SupportsAsyncClose | None,
    *,
    resource_label: str,
    close_method: str = "close",
) -> None:
    r"""Close a lazily-created async connection from a sync ``close()``.

    Raises if a ``asyncio`` event loop is currently running, since the
    async connection belongs to that loop and cannot be safely closed
    with ``asyncio.run`` from within it; the caller must use
    ``await store.aclose()`` instead. Otherwise, closes the connection
    with ``asyncio.run``, tolerating the case where the event loop that
    originally owned it (e.g. a per-test loop managed by
    pytest-asyncio) is already closed, in which case the underlying
    connection is already gone and there is nothing more to clean up.

    Args:
        aconn: The async connection to close, or ``None`` if none has
            been created yet, in which case this is a no-op.
        resource_label: A short description of the connection/backend
            (e.g. ``"SQLite"``, ``"Redis"``, ``"Postgres"``), used in
            log messages and the raised error.
        close_method: The name of the async close method to call on
            ``aconn`` (e.g. ``"close"``, ``"aclose"``).

    Raises:
        RuntimeError: If called from inside a running event loop while
            ``aconn`` is not ``None``.
    """
    if aconn is None:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        msg = (
            f"An async {resource_label} connection is open and close() was called from "
            "inside a running event loop; use `await store.aclose()` instead."
        )
        raise RuntimeError(msg)
    close: Callable[[], Coroutine[Any, Any, Any]] = getattr(aconn, close_method)
    try:
        asyncio.run(close())
    except RuntimeError:
        logger.debug(
            "Async %s connection could not be closed cleanly because its event "
            "loop is already closed",
            resource_label,
        )
