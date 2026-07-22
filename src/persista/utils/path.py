r"""Contain path utility functions."""

from __future__ import annotations

__all__ = ["prepare_store_path"]

import logging
from typing import TYPE_CHECKING

from coola.utils.path import sanitize_path

if TYPE_CHECKING:
    from pathlib import Path


logger: logging.Logger = logging.getLogger(__name__)


def prepare_store_path(path: Path | str) -> Path | str:
    """Prepare a path for use as a file-backed store's location.

    If ``path`` is the special in-memory sentinel (``":memory:"``), it is
    returned unchanged. Otherwise, ``path`` is sanitized and its parent
    directory is created if it does not already exist, so that the
    underlying backend can create the database file without failing on a
    missing directory.

    Args:
        path: The connection target -- either the in-memory sentinel
            ``":memory:"``, or a filesystem path to a database file.

    Returns:
        ``":memory:"`` unchanged, or the sanitized, absolute ``Path``
        whose parent directory is guaranteed to exist.
    """
    if isinstance(path, str) and path == ":memory:":
        return path

    path = sanitize_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Ensured parent directory exists: %s", path.parent)
    return path
