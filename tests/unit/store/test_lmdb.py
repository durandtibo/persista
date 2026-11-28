from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from persista.store import JsonCodec, LmdbStore, PickleCodec
from persista.store.lmdb import (
    _check_environment_files,
    _encode_key,
    _encode_keys,
    _encode_payload,
)
from persista.store.plan import build_plan
from persista.testing.fixtures import lmdb_available, lmdb_not_available
from persista.utils.imports import is_lmdb_available

if is_lmdb_available():
    import lmdb

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from persista.store import Codec

MAP_SIZE = 2**24


class CustomCodec(JsonCodec):
    r"""A codec with a name that no URI scheme has."""

    name = "custom"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    r"""Return the path of an environment that contains one value."""
    path = tmp_path / "data"
    with LmdbStore(path, map_size=MAP_SIZE) as store:
        store.set("1", {"a": 1})
    return path


@pytest.fixture
def store(tmp_path: Path) -> Generator[LmdbStore, None, None]:
    with LmdbStore(tmp_path / "db", map_size=MAP_SIZE) as store:
        yield store


@pytest.fixture
def filled_store(store: LmdbStore) -> LmdbStore:
    store._put_many({"1": '{"a": 1}', "2": '{"a": 2}', "3": '{"a": 3}'})
    return store


PAYLOADS = {"1": b'{"a": 1}', "2": b'{"a": 2}', "3": b'{"a": 3}'}


###############################
#     Tests for LmdbStore     #
###############################


@lmdb_not_available
def test_init_without_lmdb(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"'lmdb' package is required"):
        LmdbStore(tmp_path)


# --- constructor ---


@lmdb_available
def test_init_makes_path_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert LmdbStore("data").path == (tmp_path / "data").resolve()


@lmdb_available
def test_init_does_not_create_directory(tmp_path: Path) -> None:
    LmdbStore(tmp_path / "data")
    assert not (tmp_path / "data").exists()


@lmdb_available
def test_init_options_are_keyword_only(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        LmdbStore(tmp_path, MAP_SIZE)


@lmdb_available
@pytest.mark.parametrize("name", ["readonly", "create"])
def test_init_rejects_managed_options(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match=r"Use read_only"):
        LmdbStore(tmp_path, **{name: True})


@lmdb_available
def test_init_unsupported_codec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"needs a codec named \['json', 'pickle'\]"):
        LmdbStore(tmp_path, codec=CustomCodec())


@lmdb_available
def test_init_passes_options_to_lmdb(tmp_path: Path) -> None:
    with LmdbStore(tmp_path, map_size=MAP_SIZE, max_readers=7) as store:
        assert store.environment.info()["max_readers"] == 7


@lmdb_available
def test_init_map_size(store: LmdbStore) -> None:
    assert store.environment.info()["map_size"] == MAP_SIZE


# --- keys ---


@lmdb_available
@pytest.mark.parametrize("key", ["a", "x" * 511, "é" * 255, "a" + chr(0) + "b"])
def test_accepted_key(store: LmdbStore, key: str) -> None:
    store.set(key, {})
    assert list(store.keys()) == [key]


@lmdb_available
@pytest.mark.parametrize(
    "key",
    [
        pytest.param("", id="empty"),
        pytest.param("x" * 512, id="too_long"),
        pytest.param("é" * 256, id="too_many_bytes"),
        pytest.param(chr(0xD800), id="surrogate"),
    ],
)
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s, k: s.get(k), id="get"),
        pytest.param(lambda s, k: s.get_many(["1", k]), id="get_many"),
        pytest.param(lambda s, k: s.contains(k), id="contains"),
        pytest.param(lambda s, k: s.set(k, {}), id="set"),
        pytest.param(lambda s, k: s.set_many({"new": {}, k: {}}), id="set_many"),
        pytest.param(
            lambda s, k: s.set_many({"1": {}, k: {}}, on_conflict="raise"), id="set_many_raise"
        ),
        pytest.param(lambda s, k: s.delete(k), id="delete"),
        pytest.param(lambda s, k: s.delete_many(["1", k]), id="delete_many"),
    ],
)
def test_rejected_key_raises_and_changes_nothing(
    filled_store: LmdbStore, key: str, operation: Callable[[LmdbStore, str], Any]
) -> None:
    with pytest.raises(ValueError, match=r"A key of LmdbStore must"):
        operation(filled_store, key)
    assert dict(next(filled_store._iter_batches(10))) == PAYLOADS


# --- open / close ---


@lmdb_available
def test__open_creates_missing_directories(tmp_path: Path) -> None:
    with LmdbStore(tmp_path / "nested" / "data", map_size=MAP_SIZE):
        assert (tmp_path / "nested" / "data" / "data.mdb").is_file()


@lmdb_available
def test__open_single_file(tmp_path: Path) -> None:
    with LmdbStore(tmp_path / "nested" / "db", map_size=MAP_SIZE, subdir=False):
        assert (tmp_path / "nested" / "db").is_file()


@lmdb_available
def test__open_same_path_twice(path: Path) -> None:
    second = LmdbStore(path, map_size=MAP_SIZE)
    with (
        LmdbStore(path, map_size=MAP_SIZE),
        pytest.raises(lmdb.Error, match=r"already open in this process"),
    ):
        second.open()
    assert second.closed


@lmdb_available
def test_reopen_keeps_values(path: Path) -> None:
    with LmdbStore(path, map_size=MAP_SIZE) as store:
        assert store.get("1") == {"a": 1}


@lmdb_available
def test__close(store: LmdbStore) -> None:
    environment = store.environment
    store._close()
    with pytest.raises(lmdb.Error, match=r"closed"):
        environment.stat()


@lmdb_available
def test__close_without_open(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        LmdbStore(tmp_path)._close()
    assert caplog.messages == []


@lmdb_available
def test_environment_not_open(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"LmdbStore is not open"):
        _ = LmdbStore(tmp_path).environment


# --- read only ---


@lmdb_available
def test_read_only_reads_existing_values(path: Path) -> None:
    with LmdbStore(path, map_size=MAP_SIZE, read_only=True) as store:
        assert store.get("1") == {"a": 1}


@lmdb_available
@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.set("2", {}), id="set"),
        pytest.param(lambda s: s.set("2", {}, on_conflict="raise"), id="set_raise"),
        pytest.param(lambda s: s.delete("1"), id="delete"),
        pytest.param(lambda s: s.clear(), id="clear"),
    ],
)
def test_read_only_rejects_writes(path: Path, write: Callable[[LmdbStore], Any]) -> None:
    with LmdbStore(path, map_size=MAP_SIZE, read_only=True) as store:
        with pytest.raises(lmdb.ReadonlyError, match=r"read-only"):
            write(store)
        assert dict(next(store.iter_batches())) == {"1": {"a": 1}}


@lmdb_available
def test_read_only_does_not_create_directory(tmp_path: Path) -> None:
    store = LmdbStore(tmp_path / "data", read_only=True)
    with pytest.raises(FileNotFoundError, match=r"No LMDB environment to read"):
        store.open()
    assert not (tmp_path / "data").exists()


@lmdb_available
def test_read_only_does_not_create_files(tmp_path: Path) -> None:
    store = LmdbStore(tmp_path, read_only=True)
    with pytest.raises(FileNotFoundError, match=r"No LMDB environment to read"):
        store.open()
    assert list(tmp_path.iterdir()) == []


@lmdb_available
def test_read_only_does_not_create_lock_file(path: Path) -> None:
    (path / "lock.mdb").unlink()
    store = LmdbStore(path, read_only=True)
    with pytest.raises(FileNotFoundError, match=r"lock file .* does not exist"):
        store.open()
    assert [file.name for file in path.iterdir()] == ["data.mdb"]


@lmdb_available
def test_read_only_without_lock(path: Path) -> None:
    (path / "lock.mdb").unlink()
    with LmdbStore(path, map_size=MAP_SIZE, read_only=True, lock=False) as store:
        assert (store.get("1"), [file.name for file in path.iterdir()]) == ({"a": 1}, ["data.mdb"])


@lmdb_available
def test_read_only_single_file(tmp_path: Path) -> None:
    with LmdbStore(tmp_path / "db", map_size=MAP_SIZE, subdir=False) as store:
        store.set("1", {})
    with LmdbStore(tmp_path / "db", map_size=MAP_SIZE, subdir=False, read_only=True) as store:
        assert store.contains("1")


# --- primitives ---


@lmdb_available
def test__get_many(filled_store: LmdbStore) -> None:
    assert filled_store._get_many(["3", "missing", "1", "3"]) == {
        "3": PAYLOADS["3"],
        "1": PAYLOADS["1"],
    }


@lmdb_available
@pytest.mark.parametrize(("key", "expected"), [("1", {"1": PAYLOADS["1"]}), ("missing", {})])
def test__get_many_one_key(filled_store: LmdbStore, key: str, expected: dict) -> None:
    assert filled_store._get_many([key]) == expected


@lmdb_available
@pytest.mark.parametrize("payload", ['{"é": 1}', '{"é": 1}'.encode()])
def test__put_many(store: LmdbStore, payload: str | bytes) -> None:
    store._put_many({"a": payload})
    assert store._get_many(["a"]) == {"a": '{"é": 1}'.encode()}


@lmdb_available
def test__put_many_full_map_writes_nothing(tmp_path: Path) -> None:
    with LmdbStore(tmp_path, map_size=2**16) as store:
        with pytest.raises(lmdb.MapFullError, match=r"MDB_MAP_FULL"):
            store._put_many({"a": b"1", "b": b"x" * 2**17})
        assert store._count() == 0


@lmdb_available
def test__update(filled_store: LmdbStore) -> None:
    filled_store._update(["1", "4"], lambda existing: {"4": existing["1"]})
    assert filled_store._get_many(["1", "4"]) == {"1": PAYLOADS["1"], "4": PAYLOADS["1"]}


@lmdb_available
def test__update_gives_the_existing_payloads_to_the_plan(filled_store: LmdbStore) -> None:
    received: list[dict] = []
    filled_store._update(["4", "1"], lambda existing: received.append(existing) or {})
    assert received == [{"1": PAYLOADS["1"]}]


@lmdb_available
def test__update_plan_raises_writes_nothing(filled_store: LmdbStore) -> None:
    plan = build_plan({"4": "{}", "1": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store._update(["4", "1"], plan)
    assert filled_store._count() == 3


@lmdb_available
def test__delete_many(filled_store: LmdbStore) -> None:
    filled_store._delete_many(["1", "missing", "1", "3"])
    assert filled_store._get_many(["1", "2", "3"]) == {"2": PAYLOADS["2"]}


@lmdb_available
def test__clear(filled_store: LmdbStore) -> None:
    filled_store._clear()
    assert filled_store._count() == 0


@lmdb_available
def test__clear_then_write(filled_store: LmdbStore) -> None:
    filled_store._clear()
    filled_store._put_many({"4": b"{}"})
    assert filled_store._get_many(["1", "4"]) == {"4": b"{}"}


@lmdb_available
def test__count(filled_store: LmdbStore) -> None:
    assert filled_store._count() == 3


@lmdb_available
def test__contains_many(filled_store: LmdbStore) -> None:
    assert filled_store._contains_many(["1", "missing", "1", "3"]) == {"1", "3"}


@lmdb_available
@pytest.mark.parametrize(
    ("batch_size", "expected"),
    [(1, [["1"], ["2"], ["3"]]), (2, [["1", "2"], ["3"]]), (3, [["1", "2", "3"]])],
)
def test__iter_batches(filled_store: LmdbStore, batch_size: int, expected: list[list[str]]) -> None:
    assert [list(batch) for batch in filled_store._iter_batches(batch_size)] == expected


@lmdb_available
def test__iter_batches_payloads(filled_store: LmdbStore) -> None:
    assert list(filled_store._iter_batches(10)) == [PAYLOADS]


@lmdb_available
def test__iter_batches_empty_store(store: LmdbStore) -> None:
    assert list(store._iter_batches(2)) == []


@lmdb_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_skips_keys_deleted_since_the_snapshot(
    filled_store: LmdbStore, method: str
) -> None:
    iterator = getattr(filled_store, method)(1)
    next(iterator)
    filled_store._delete_many(["2"])
    assert [list(batch) for batch in iterator] == [["3"]]


@lmdb_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_does_not_yield_empty_batches(filled_store: LmdbStore, method: str) -> None:
    iterator = getattr(filled_store, method)(1)
    next(iterator)
    filled_store._clear()
    assert list(iterator) == []


@lmdb_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_does_not_yield_keys_written_after_the_snapshot(
    filled_store: LmdbStore, method: str
) -> None:
    iterator = getattr(filled_store, method)(1)
    next(iterator)
    filled_store._put_many({"4": b"{}"})
    assert [list(batch) for batch in iterator] == [["2"], ["3"]]


@lmdb_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_keeps_no_reader_between_batches(filled_store: LmdbStore, method: str) -> None:
    iterator = getattr(filled_store, method)(1)
    next(iterator)
    # The table of the readers has no transaction that holds a snapshot.
    assert [line.split()[-1] for line in filled_store.environment.readers().splitlines()[1:]] in (
        [],
        ["-"],
    )


@lmdb_available
@pytest.mark.parametrize(
    ("batch_size", "expected"),
    [(1, [["1"], ["2"], ["3"]]), (2, [["1", "2"], ["3"]]), (3, [["1", "2", "3"]])],
)
def test__iter_key_batches(
    filled_store: LmdbStore, batch_size: int, expected: list[list[str]]
) -> None:
    assert list(filled_store._iter_key_batches(batch_size)) == expected


@lmdb_available
def test__iter_key_batches_empty_store(store: LmdbStore) -> None:
    assert list(store._iter_key_batches(2)) == []


@lmdb_available
def test__snapshot_keys(filled_store: LmdbStore) -> None:
    assert filled_store._snapshot_keys() == [b"1", b"2", b"3"]


# --- uri ---


@lmdb_available
@pytest.mark.parametrize(
    ("codec", "scheme"), [(JsonCodec(), "lmdb"), (PickleCodec(), "lmdb+pickle")]
)
def test_to_uri(codec: Codec, scheme: str) -> None:
    assert LmdbStore("/data/a dir", codec=codec).to_uri() == f"{scheme}:/data/a%20dir"


@lmdb_available
@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec()])
def test_from_uri_gives_the_path_and_the_codec(tmp_path: Path, codec: Codec) -> None:
    restored = LmdbStore.from_uri(LmdbStore(tmp_path, codec=codec).to_uri())
    assert (restored.path, type(restored._codec)) == (tmp_path.resolve(), type(codec))


@lmdb_available
def test_from_uri_passes_the_options(path: Path) -> None:
    uri = LmdbStore(path).to_uri()
    with LmdbStore.from_uri(uri, map_size=2**25) as store:
        assert store.environment.info()["map_size"] == 2**25


@lmdb_available
def test_from_uri_read_only(path: Path) -> None:
    uri = LmdbStore(path).to_uri()
    with (
        LmdbStore.from_uri(uri, read_only=True) as store,
        pytest.raises(lmdb.ReadonlyError, match=r"read-only"),
    ):
        store.set("2", {})


@lmdb_available
def test_from_uri_keeps_given_codec(tmp_path: Path) -> None:
    codec = PickleCodec()
    uri = LmdbStore(tmp_path, codec=codec).to_uri()
    assert LmdbStore.from_uri(uri, codec=codec)._codec is codec


@lmdb_available
def test_from_uri_codec_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"does not match the scheme"):
        LmdbStore.from_uri(LmdbStore(tmp_path).to_uri(), codec=PickleCodec())


@lmdb_available
@pytest.mark.parametrize("uri", ["sqlite:/data", "lmdb+json:/data", "/data"])
def test_from_uri_other_scheme(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid scheme"):
        LmdbStore.from_uri(uri)


# --- repr ---


@lmdb_available
def test_repr(filled_store: LmdbStore) -> None:
    assert repr(filled_store) == (
        f"LmdbStore(\n  (path): {filled_store.path}\n  (closed): False\n)"
    )


@lmdb_available
def test_repr_reads_nothing(filled_store: LmdbStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filled_store, "_count", MagicMock(side_effect=AssertionError("query")))
    assert "LmdbStore(" in repr(filled_store)


@lmdb_available
def test__get_repr_kwargs_closed(tmp_path: Path) -> None:
    assert LmdbStore(tmp_path)._get_repr_kwargs() == {
        "path": str(tmp_path.resolve()),
        "closed": True,
    }


@lmdb_available
def test__get_repr_kwargs_options(tmp_path: Path) -> None:
    codec = PickleCodec()
    store = LmdbStore(tmp_path, codec=codec, read_only=True, max_readers=7)
    assert store._get_repr_kwargs() == {
        "path": str(tmp_path.resolve()),
        "closed": True,
        "codec": codec,
        "read_only": True,
    }


#################################
#     Tests for _encode_key     #
#################################


@pytest.mark.parametrize(
    ("key", "encoded"), [("a", b"a"), ("é", b"\xc3\xa9"), ("x" * 511, b"x" * 511)]
)
def test__encode_key(key: str, encoded: bytes) -> None:
    assert _encode_key(key) == encoded


@pytest.mark.parametrize(("key", "size"), [("", 0), ("x" * 512, 512), ("é" * 256, 512)])
def test__encode_key_invalid_size(key: str, size: int) -> None:
    with pytest.raises(ValueError, match=rf"1 to 511 UTF-8 bytes, not {size}:"):
        _encode_key(key)


def test__encode_key_lone_surrogate() -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        _encode_key(chr(0xD800))


##################################
#     Tests for _encode_keys     #
##################################


@pytest.mark.parametrize(
    ("keys", "encoded"),
    [([], []), (["b", "é", "b"], [b"b", b"\xc3\xa9", b"b"]), (["x" * 511], [b"x" * 511])],
)
def test__encode_keys(keys: list[str], encoded: list[bytes]) -> None:
    assert _encode_keys(keys) == encoded


@pytest.mark.parametrize("key", ["", "x" * 512])
def test__encode_keys_invalid_size(key: str) -> None:
    with pytest.raises(ValueError, match=r"1 to 511 UTF-8 bytes"):
        _encode_keys(["a", key])


def test__encode_keys_lone_surrogate() -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        _encode_keys(["a", chr(0xD800)])


#####################################
#     Tests for _encode_payload     #
#####################################


@pytest.mark.parametrize("payload", ["é", "é".encode()])
def test__encode_payload(payload: str | bytes) -> None:
    assert _encode_payload(payload) == "é".encode()


##############################################
#     Tests for _check_environment_files     #
##############################################


@pytest.mark.parametrize(
    ("names", "subdir", "lock"),
    [
        pytest.param(["db/data.mdb", "db/lock.mdb"], True, True, id="directory"),
        pytest.param(["db/data.mdb"], True, False, id="directory_without_lock"),
        pytest.param(["db", "db-lock"], False, True, id="file"),
        pytest.param(["db"], False, False, id="file_without_lock"),
    ],
)
def test__check_environment_files(
    tmp_path: Path, names: list[str], subdir: bool, lock: bool
) -> None:
    for name in names:
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).touch()
    assert _check_environment_files(tmp_path / "db", subdir=subdir, lock=lock) is None


@pytest.mark.parametrize("subdir", [True, False])
def test__check_environment_files_no_data_file(tmp_path: Path, subdir: bool) -> None:
    with pytest.raises(FileNotFoundError, match=r"No LMDB environment to read"):
        _check_environment_files(tmp_path / "db", subdir=subdir, lock=False)


@pytest.mark.parametrize(("name", "subdir"), [("db/data.mdb", True), ("db", False)])
def test__check_environment_files_no_lock_file(tmp_path: Path, name: str, subdir: bool) -> None:
    (tmp_path / name).parent.mkdir(exist_ok=True)
    (tmp_path / name).touch()
    with pytest.raises(FileNotFoundError, match=r"lock file .* does not exist"):
        _check_environment_files(tmp_path / "db", subdir=subdir, lock=True)


@lmdb_available
def test_open_checks_the_driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = LmdbStore(tmp_path)
    error = RuntimeError("the driver is missing")
    monkeypatch.setattr("persista.store.lmdb.check_lmdb", MagicMock(side_effect=error))
    with pytest.raises(RuntimeError, match=r"the driver is missing"):
        store.open()
    assert store.closed
