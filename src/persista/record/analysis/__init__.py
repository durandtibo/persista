r"""Contain code to analyze records."""

from __future__ import annotations

__all__ = [
    "MetadataStats",
    "compute_metadata_stats",
    "count_approx_duplicate_records",
    "find_duplicate_record_ids",
    "print_metadata_stats_report",
]

from persista.record.analysis.dedup import find_duplicate_record_ids
from persista.record.analysis.dedup_approx import (
    count_approx_duplicate_records,
)
from persista.record.analysis.metadata_print import print_metadata_stats_report
from persista.record.analysis.metadata_stats import (
    MetadataStats,
    compute_metadata_stats,
)
