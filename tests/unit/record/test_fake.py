from __future__ import annotations

from unittest.mock import patch

import pytest

from persista.record.fake import generate_fake_records
from persista.record.record import Record
from persista.testing.fixtures import faker_available

MODULE = "persista.record.fake"

###########################################
#     Tests for generate_fake_records     #
###########################################


# --- basic generation ---


@faker_available
def test_generate_fake_records_default_count() -> None:
    records = generate_fake_records()
    assert len(records) == 5


@faker_available
def test_generate_fake_records_custom_count() -> None:
    records = generate_fake_records(n=10)
    assert len(records) == 10


@faker_available
def test_generate_fake_records_zero_returns_empty_list() -> None:
    assert generate_fake_records(n=0) == []


@faker_available
def test_generate_fake_records_negative_raises() -> None:
    with pytest.raises(ValueError, match=r"'n' must be non-negative"):
        generate_fake_records(n=-1)


@faker_available
def test_generate_fake_records_returns_record_instances() -> None:
    records = generate_fake_records(n=3)
    assert all(isinstance(r, Record) for r in records)


# --- ids ---


@faker_available
def test_generate_fake_records_ids_are_sequential() -> None:
    records = generate_fake_records(n=3)
    assert [r.id for r in records] == ["rec-0", "rec-1", "rec-2"]


@faker_available
def test_generate_fake_records_ids_are_unique() -> None:
    records = generate_fake_records(n=20)
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids))


# --- metadata ---


@faker_available
def test_generate_fake_records_metadata_has_author_and_topic() -> None:
    records = generate_fake_records(n=3)
    for r in records:
        assert "author" in r.metadata
        assert "topic" in r.metadata
        assert isinstance(r.metadata["author"], str)
        assert isinstance(r.metadata["topic"], str)


@faker_available
def test_generate_fake_records_metadata_does_not_contain_extra_keys() -> None:
    records = generate_fake_records(n=1)
    assert set(records[0].metadata.keys()) == {"author", "topic"}


@faker_available
def test_generate_fake_records_metadata_values_are_forwarded_from_faker() -> None:
    with patch(f"{MODULE}.faker.Faker") as mock_faker_cls:
        mock_fake = mock_faker_cls.return_value
        mock_fake.name.return_value = "Jane Doe"
        mock_fake.word.return_value = "topic"

        records = generate_fake_records(n=1)

        assert records[0].metadata == {"author": "Jane Doe", "topic": "topic"}


# --- seeding / determinism ---


@faker_available
def test_generate_fake_records_same_seed_same_output() -> None:
    records1 = generate_fake_records(n=5, seed=42)
    records2 = generate_fake_records(n=5, seed=42)
    assert [r.metadata for r in records1] == [r.metadata for r in records2]


@faker_available
def test_generate_fake_records_different_seed_likely_different_output() -> None:
    """Not a strict guarantee (Faker output could theoretically
    coincide), but with two different seeds across a batch of names and
    words, an accidental collision across the whole batch is
    astronomically unlikely, so this is a reliable regression check."""
    records1 = generate_fake_records(n=5, seed=1)
    records2 = generate_fake_records(n=5, seed=2)
    assert [r.metadata for r in records1] != [r.metadata for r in records2]


@faker_available
def test_generate_fake_records_no_seed_calls_do_not_raise() -> None:
    # Sanity check that omitting `seed` (the common case) works at all.
    records = generate_fake_records(n=2, seed=None)
    assert len(records) == 2


@faker_available
def test_generate_fake_records_seed_is_forwarded_to_faker_seed() -> None:
    with patch(f"{MODULE}.faker.Faker") as mock_faker_cls:
        mock_fake = mock_faker_cls.return_value
        mock_fake.name.return_value = "name"
        mock_fake.word.return_value = "word"

        generate_fake_records(n=1, seed=123)

        mock_faker_cls.seed.assert_called_once_with(123)


@faker_available
def test_generate_fake_records_no_seed_does_not_call_faker_seed() -> None:
    with patch(f"{MODULE}.faker.Faker") as mock_faker_cls:
        mock_fake = mock_faker_cls.return_value
        mock_fake.name.return_value = "name"
        mock_fake.word.return_value = "word"

        generate_fake_records(n=1, seed=None)

        mock_faker_cls.seed.assert_not_called()


# --- optional dependency guard ---


@faker_available
def test_generate_fake_records_raises_if_faker_unavailable() -> None:
    with (
        patch(f"{MODULE}.check_faker", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        generate_fake_records(n=1)


@faker_available
def test_generate_fake_records_checks_availability_before_validating_n() -> None:
    """The availability check should happen unconditionally, even for
    inputs (like a negative n) that would otherwise short-circuit with a
    different error — so callers always get an accurate diagnosis of a
    missing dependency rather than a misleading ValueError."""
    with patch(f"{MODULE}.check_faker", side_effect=RuntimeError("missing")) as mock_check:
        with pytest.raises(RuntimeError, match="missing"):
            generate_fake_records(n=-1)
        mock_check.assert_called_once()
