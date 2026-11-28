r"""Contain code to analyze records.

The analyses that compare metadata values use the equality of
:mod:`persista.record.equality`: ``1``, ``"1"`` and ``True`` differ, ``1``
equals ``1.0``, and a value that cannot be compared raises ``TypeError``
(``ValueError`` for ``NaN``) instead of being ignored. No function modifies
its input, and each accepts any iterable of records, consumed once.
"""

from __future__ import annotations

__all__ = [
    "compute_metadata_stats",
    "compute_schema_shapes",
    "compute_value_frequency",
    "count_approx_duplicate_records",
    "diff_records",
    "find_duplicate_record_ids",
    "find_id_collisions",
    "find_near_duplicate_record_ids",
    "find_orphan_references",
    "print_metadata_stats_report",
]

from persista.record.analysis.dedup import find_duplicate_record_ids
from persista.record.analysis.dedup_approx import (
    count_approx_duplicate_records,
)
from persista.record.analysis.diff import diff_records
from persista.record.analysis.id_collision import find_id_collisions
from persista.record.analysis.metadata_print import print_metadata_stats_report
from persista.record.analysis.metadata_stats import compute_metadata_stats
from persista.record.analysis.near_dedup import find_near_duplicate_record_ids
from persista.record.analysis.reference_check import find_orphan_references
from persista.record.analysis.schema_shapes import compute_schema_shapes
from persista.record.analysis.value_frequency import compute_value_frequency
