"""Pretty-print record metadata statistics reports using rich."""

from __future__ import annotations

__all__ = ["print_metadata_stats_report"]

from typing import Any

from rich import get_console
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _format_count(count: int, total: int) -> str:
    """Format a count alongside its percentage of total.

    Args:
        count: The sub-count to display (e.g. number of records
            missing a given key).
        total: The total record count, used as the percentage
            denominator.

    Returns:
        A string like ``"3 (0.3%)"``, or ``"3 (0.0%)"`` if ``total``
        is falsy (avoids a division by zero).

    Examples:
        >>> _format_count(3, 1000)
        '3 (0.3%)'
        >>> _format_count(0, 0)
        '0 (0.0%)'
    """
    pct = (count / total * 100) if total else 0.0
    return f"{count} ({pct:.1f}%)"


def _build_overview_line(stats: dict[str, Any], count: int) -> Text:
    """Build the "N records · N distinct keys" summary line shown at the
    top of the report.

    Args:
        stats: The full stats report dict. Only ``distinct_keys_seen``
            is read from it.
        count: Total record count, shown as the first part of the
            line (passed separately since callers already need to
            compute/validate it).

    Returns:
        A ``rich.text.Text`` object with the record count in bold and
        the distinct-key count in dim, separated by a middle dot.

    Examples:
        >>> text = _build_overview_line({"distinct_keys_seen": 2}, 100)
        >>> text.plain
        '100 records  ·  2 distinct keys'
    """
    overview = Text()
    overview.append(f"{count:,} records", style="bold")
    overview.append("  ·  ")
    overview.append(f"{stats.get('distinct_keys_seen', 0)} distinct keys", style="dim")
    return overview


def _build_summary_table(stats: dict[str, Any], count: int) -> Table:
    """Build the "Metric" / "Value" summary table.

    Renders a "keys per record" section (average/min/max) and a "data
    quality" section (missing metadata count) as a borderless
    two-column table with right-aligned values.

    Args:
        stats: The full stats report dict (as returned by
            ``compute_metadata_stats``).
        count: Total record count, used as the percentage
            denominator for the missing-metadata row.

    Returns:
        A borderless ``rich.table.Table``.

    Examples:
        >>> stats = {
        ...     "avg_keys": 2.0, "min_keys": 2, "max_keys": 2,
        ...     "missing_metadata_count": 0,
        ... }
        >>> table = _build_summary_table(stats, 100)
        >>> isinstance(table, Table)
        True
    """
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    def row(label: str, value: str) -> None:
        table.add_row(label, value)

    def section(label: str) -> None:
        table.add_row(f"[dim]{label}[/dim]", "")

    section("keys per record")
    row("  Average", f"{stats['avg_keys']:.2f}")
    row("  Min", str(stats["min_keys"]))
    row("  Max", str(stats["max_keys"]))

    section("data quality")
    row("  Missing metadata", _format_count(stats["missing_metadata_count"], count))

    return table


def _build_key_flags(info: dict[str, Any]) -> str:
    """Build the data-quality flags string for a single metadata key.

    Args:
        info: The per-key stats dict (one value of ``stats["per_key"]``),
            expected to contain ``missing_in_records``, ``value_types``,
            and ``none_or_empty_count``.

    Returns:
        A yellow, comma-joined list of flags (``"missing values"``,
        ``"mixed types"``, ``"has None/empty"``) - whichever apply -
        or a green ``"ok"`` if none apply.

    Examples:
        >>> _build_key_flags({
        ...     "missing_in_records": 0, "value_types": ["str"],
        ...     "none_or_empty_count": 0,
        ... })
        '[green]ok[/green]'
    """
    flags = []
    if info["missing_in_records"] > 0:
        flags.append("missing values")
    if len(info["value_types"]) > 1:
        flags.append("mixed types")
    if info["none_or_empty_count"] > 0:
        flags.append("has None/empty")

    if not flags:
        return "[green]ok[/green]"
    return f"[yellow]{', '.join(flags)}[/yellow]"


def _build_key_sample(info: dict[str, Any]) -> str:
    """Build the "Sample values" cell for a single metadata key.

    Args:
        info: The per-key stats dict, expected to contain
            ``unique_values_sample`` and
            ``unique_values_sample_truncated``.

    Returns:
        A comma-joined string of sampled values, with a trailing
        ``"…"`` appended if the sample was truncated.

    Examples:
        >>> _build_key_sample({
        ...     "unique_values_sample": ["a", "b"],
        ...     "unique_values_sample_truncated": True,
        ... })
        'a, b, …'
    """
    sample = ", ".join(str(v) for v in info["unique_values_sample"])
    if info["unique_values_sample_truncated"]:
        sample = f"{sample}, …" if sample else "…"
    return sample


def _build_per_key_table(per_key: dict[str, Any], count: int) -> Table:
    """Build the "Metadata Keys" table, one row per metadata key.

    Args:
        per_key: The ``stats["per_key"]`` dict mapping each metadata
            key to its stats dict.
        count: Total record count, used as the percentage
            denominator for the "Present" and "None/Empty" columns.

    Returns:
        A ``rich.table.Table`` titled "Metadata Keys" with one row per
        key, sorted in the order given by ``per_key``.

    Examples:
        >>> per_key = {
        ...     "source": {
        ...         "present_in_records": 2, "missing_in_records": 0,
        ...         "value_types": ["str"], "none_or_empty_count": 0,
        ...         "unique_values_sample": ["a.pdf"],
        ...         "unique_values_sample_truncated": False,
        ...     }
        ... }
        >>> table = _build_per_key_table(per_key, 2)
        >>> isinstance(table, Table)
        True
    """
    table = Table(
        show_header=True, header_style="bold", title="Metadata Keys", title_justify="left"
    )
    table.add_column("Key", style="cyan")
    table.add_column("Present", justify="right")
    table.add_column("Types")
    table.add_column("None/Empty", justify="right")
    table.add_column("Sample values")
    table.add_column("Flags")

    for key, info in per_key.items():
        table.add_row(
            key,
            _format_count(info["present_in_records"], count),
            ", ".join(info["value_types"]),
            _format_count(info["none_or_empty_count"], count),
            _build_key_sample(info),
            _build_key_flags(info),
        )

    return table


def print_metadata_stats_report(
    stats: dict[str, Any],
    *,
    title: str = "Metadata Report",
    console: Console | None = None,
) -> None:
    """Render a record-metadata-stats report (from
    ``compute_metadata_stats``) as an overview line, a summary table,
    and a per-key breakdown table, inside a cyan panel that shrinks to
    fit its content rather than stretching to the full terminal width.

    This function orchestrates the report layout by delegating each
    section to a dedicated builder: ``_build_overview_line`` (record/key
    count summary), ``_build_summary_table`` (keys-per-record / data
    quality), and ``_build_per_key_table`` (one row per metadata key,
    with sampled values and data-quality flags).

    Args:
        stats: The dict returned by ``compute_metadata_stats`` (or
            ``MetadataStats.to_dict``). Expected to contain a ``count``
            key; all other keys are read defensively via ``[...]``/
            ``.get(...)``, so a partial dict for an empty corpus (e.g.
            ``count=0``) still renders correctly.
        title: Panel title shown above the report, at the top-left of
            the panel border.
        console: An existing ``rich.console.Console`` to print to.
            Defaults to the shared rich console via ``get_console()``.

    Returns:
        None. Output is printed directly to ``console``.

    Examples:
        >>> stats = {
        ...     "count": 2, "missing_metadata_count": 0,
        ...     "avg_keys": 1.5, "min_keys": 1, "max_keys": 2,
        ...     "distinct_keys_seen": 2,
        ...     "per_key": {
        ...         "source": {
        ...             "present_in_records": 2, "missing_in_records": 0,
        ...             "value_types": ["str"], "none_or_empty_count": 0,
        ...             "unique_values_sample": ["a.pdf", "b.pdf"],
        ...             "unique_values_sample_truncated": False,
        ...         },
        ...     },
        ... }
        >>> print_metadata_stats_report(stats)  # doctest: +SKIP
    """
    console = console or get_console()

    panel_title = f"[bold]{title}[/bold]"
    count = stats["count"]
    per_key: dict[str, Any] = stats.get("per_key", {})

    renderables: list[Any] = [
        _build_overview_line(stats, count),
        Text(),
        _build_summary_table(stats, count),
    ]
    if per_key:
        renderables.append(Text())
        renderables.append(_build_per_key_table(per_key, count))

    console.print(
        Panel(
            Group(*renderables),
            title=panel_title,
            title_align="left",
            border_style="cyan",
            expand=False,
        )
    )
