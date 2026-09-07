r"""Define the ``Record`` container and helpers to filter and sort
collections of records by their metadata."""

from __future__ import annotations

__all__ = [
    "Record",
    "filter_by_metadata",
    "filter_by_metadata_range",
    "filter_by_metadata_values",
    "sort_by_metadata",
]

from persista.record.filter import (
    filter_by_metadata,
    filter_by_metadata_range,
    filter_by_metadata_values,
)
from persista.record.record import Record
from persista.record.sort import sort_by_metadata
