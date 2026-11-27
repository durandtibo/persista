r"""Provide the plan of a write that depends on the existing values."""

from __future__ import annotations

__all__ = ["build_plan"]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.store.codec import Codec
    from persista.store.types import OnConflict, Payload, Plan


def build_plan(items: dict[str, Payload], on_conflict: OnConflict, codec: Codec) -> Plan:
    r"""Build the plan that writes ``items`` with a conflict strategy.

    :class:`~persista.store.BaseStore` gives this plan to the ``_update``
    method of a backend, which reads the existing keys, calls the plan,
    and writes its result atomically.

    Args:
        items: The payloads to write, keyed by their unique key. The
            plan does not modify it.
        on_conflict: The normalized strategy for the keys that already
            exist. See :meth:`~persista.store.BaseStore.set` for the
            meaning of each option.
        codec: The codec of the store, used by ``"merge"`` to decode the
            two values and encode the merged one.

    Returns:
        A function that takes the payloads of the existing keys and
        returns the payloads to write. It raises ``KeyError`` if
        ``on_conflict`` is ``"raise"`` and a key of ``items`` exists.

    Example:
        ```pycon
        >>> from persista.store import JsonCodec
        >>> from persista.store.plan import build_plan
        >>> plan = build_plan({"a": '{"y": 2}', "b": '{"y": 3}'}, "merge", JsonCodec())
        >>> plan({"a": '{"x": 1}'})
        {'a': '{"x": 1, "y": 2}', 'b': '{"y": 3}'}

        ```
    """

    def plan(existing: dict[str, Payload]) -> dict[str, Payload]:
        r"""Return the payloads to write.

        Args:
            existing: The payloads of the keys that exist in the store.
                Keys that are not in ``items`` are ignored.

        Returns:
            The payloads to write.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and a key of
                ``items`` exists.
        """
        conflicts = items.keys() & existing.keys()
        if not conflicts or on_conflict == "overwrite":
            return dict(items)
        if on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)
        if on_conflict == "skip":
            return {key: payload for key, payload in items.items() if key not in conflicts}
        return {
            key: (
                codec.encode({**codec.decode(existing[key]), **codec.decode(payload)})
                if key in conflicts
                else payload
            )
            for key, payload in items.items()
        }

    return plan
