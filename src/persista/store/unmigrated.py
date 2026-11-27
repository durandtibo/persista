r"""Provide the base class of the stores that do not use the primitives of
``BaseStore`` yet."""

from __future__ import annotations

__all__ = ["UnmigratedStore"]

from typing import Any, NoReturn

from persista.store.base import BaseStore


class UnmigratedStore(BaseStore):
    r"""Define a temporary base class for the stores that implement the
    public methods of :class:`~persista.store.BaseStore` themselves.

    Such a store overrides every public method that touches its backend,
    so the primitives of :class:`~persista.store.BaseStore` are never
    called. This class gives them a placeholder, so that the store can be
    instantiated. Such a store does not call ``BaseStore.__init__``,
    and takes no codec.

    It is an internal class, which will be removed once every store of
    ``persista`` implements the primitives. Do not use it in a custom
    store: implement the primitives of
    :class:`~persista.store.BaseStore` instead.

    Example:
        ```pycon
        >>> from persista.store import RedisStore
        >>> from persista.store.unmigrated import UnmigratedStore
        >>> issubclass(RedisStore, UnmigratedStore)
        True

        ```
    """

    def _unmigrated_primitive(self, *args: Any, **kwargs: Any) -> NoReturn:
        r"""Report a call to a primitive that the store does not have.

        Args:
            *args: The arguments of the primitive, which are ignored.
            **kwargs: The keyword arguments of the primitive, which are
                ignored.

        Raises:
            NotImplementedError: Always.
        """
        msg = f"{type(self).__name__} does not implement the primitives of BaseStore"
        raise NotImplementedError(msg)

    _open = _unmigrated_primitive
    _close = _unmigrated_primitive
    _get_many = _unmigrated_primitive
    _put_many = _unmigrated_primitive
    _update = _unmigrated_primitive
    _delete_many = _unmigrated_primitive
    _clear = _unmigrated_primitive
    _count = _unmigrated_primitive
    _iter_batches = _unmigrated_primitive
