from __future__ import annotations

from persista.record import Record
from persista.record.analysis import find_id_collisions

########################################
#     Tests for find_id_collisions     #
########################################


def test_find_id_collisions_no_collision_unique_ids() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert find_id_collisions(records) == {}


def test_find_id_collisions_repeated_id_same_metadata_not_a_collision() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "x"}),
    ]
    assert find_id_collisions(records) == {}


def test_find_id_collisions_repeated_id_different_metadata() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}]}


def test_find_id_collisions_multiple_distinct_variants() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "z"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}, {"source": "z"}]}


def test_find_id_collisions_only_colliding_ids_included() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
        Record(id="b", metadata={"source": "z"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}]}


def test_find_id_collisions_empty_input() -> None:
    assert find_id_collisions([]) == {}


def test_find_id_collisions_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})
        yield Record(id="a", metadata={"source": "y"})

    assert find_id_collisions(gen()) == {"a": [{"source": "x"}, {"source": "y"}]}
