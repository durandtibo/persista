r"""Contain functions to generate fake records.

It is designed to be used for testing and debugging purposes.
"""

from __future__ import annotations

__all__ = ["generate_fake_records"]

from typing import TYPE_CHECKING

from persista.record.record import Record
from persista.utils.imports import check_faker, is_faker_available

if TYPE_CHECKING or is_faker_available():  # pragma: no cover
    import faker


def generate_fake_records(
    n: int = 5,
    seed: int | None = None,
) -> list[Record]:
    """Generate synthetic Records with Faker-generated metadata.

    Each record gets a unique ``id`` (``"rec-{i}"``) and metadata
    containing a fake author name and a single-word topic.

    Args:
        n: Number of records to generate. Must be non-negative;
            ``n=0`` returns an empty list.
        seed: Optional seed for reproducible output, scoped to the
            ``Faker`` instance used internally by this call and not to
            Faker's shared, process-wide generator. If ``None``,
            content differs on every call.

    Returns:
        A list of ``n`` Record objects, each with a distinct ``id``
            and independently generated metadata.

    Raises:
        ValueError: If ``n`` is negative.
        RuntimeError: If the optional ``faker`` dependency is not
            installed.

    Example:
        ```pycon
        >>> from persista.record.fake import generate_fake_records
        >>> records = generate_fake_records(n=3, seed=42)
        >>> len(records)
        3
        >>> [record.id for record in records]
        ['rec-0', 'rec-1', 'rec-2']

        ```
    """
    check_faker()

    if n < 0:
        msg = f"'n' must be non-negative, got {n}."
        raise ValueError(msg)

    fake = faker.Faker()
    if seed is not None:
        fake.seed_instance(seed)

    return [
        Record(
            id=f"rec-{i}",
            metadata={"author": fake.name(), "topic": fake.word()},
        )
        for i in range(n)
    ]
