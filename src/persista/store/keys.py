r"""Provide helpers for working with the output of
:meth:`~persista.store.base.BaseStore.contains_many`."""

from __future__ import annotations

__all__ = ["split_present_missing"]


def split_present_missing(keys: list[str], flags: list[bool]) -> tuple[list[str], list[str]]:
    """Split keys into present and missing lists based on flags.

    Args:
        keys: The keys to split.
        flags: The presence flags for each key, in the same order as
            ``keys``, e.g. the output of
            :meth:`~persista.store.base.BaseStore.contains_many`.

    Returns:
        A ``(present, missing)`` tuple, each a list of keys in the
        same relative order as ``keys``.
    """
    present = []
    missing = []
    for key, flag in zip(keys, flags, strict=True):
        (present if flag else missing).append(key)
    return present, missing
