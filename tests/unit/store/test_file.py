from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from persista.store import FileStore, JsonCodec, PickleCodec
from persista.store.file import (
    _ESCAPE_OR_UPPER,
    _decode_file_name,
    _encode_file_name,
    _escape_upper,
    _find_shadowed_names,
    _write_file,
)
from persista.store.plan import build_plan

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from persista.store import Codec


def _ignores_case() -> bool:
    r"""Indicate whether the file system of the temporary directory
    ignores the case of the file names."""
    with tempfile.TemporaryDirectory() as path:
        (Path(path) / "a").touch()
        return (Path(path) / "A").exists()


ignores_case = pytest.mark.skipif(
    not _ignores_case(), reason="Requires a file system that ignores case"
)


class CustomCodec(JsonCodec):
    r"""A codec with a name that no URI scheme has."""

    name = "custom"


@pytest.fixture
def store(tmp_path: Path) -> Generator[FileStore, None, None]:
    with FileStore(tmp_path / "data") as store:
        yield store


@pytest.fixture
def filled_store(store: FileStore) -> FileStore:
    store._put_many({"1": '{"a": 1}', "2": '{"a": 2}', "3": '{"a": 3}'})
    return store


PAYLOADS = {"1": b'{"a": 1}', "2": b'{"a": 2}', "3": b'{"a": 3}'}


def file_names(store: FileStore) -> list[str]:
    r"""Return the names of the files of the directory of a store."""
    return list_directory(store.path)


def list_directory(path: Path) -> list[str]:
    r"""Return the sorted names of the files of a directory."""
    return sorted(file.name for file in path.iterdir())


def occupy_name(store: FileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    r"""Make the store behave as on a file system that ignores case,
    with the file ``User.json`` that occupies the name ``user.json``."""
    (store.path / "User.json").write_text('{"old": true}')
    store._shadowed = {"user.json"}
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: path.name == "user.json" or exists(path))


###############################
#     Tests for FileStore     #
###############################


# --- constructor ---


def test_init_makes_path_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert FileStore("data").path == (tmp_path / "data").resolve()


def test_init_does_not_create_directory(tmp_path: Path) -> None:
    FileStore(tmp_path / "data")
    assert not (tmp_path / "data").exists()


def test_init_path_that_is_a_file(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_text("not a directory")
    with pytest.raises(NotADirectoryError, match=r"path must be a directory"):
        FileStore(path)


def test_init_options_are_keyword_only(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        FileStore(tmp_path, PickleCodec())


def test_init_unknown_option(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"unexpected keyword argument"):
        FileStore(tmp_path, indent=2)


def test_init_unsupported_codec(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"needs a codec named \['json', 'pickle'\]"):
        FileStore(tmp_path, codec=CustomCodec())


@pytest.mark.parametrize(("codec", "name"), [(JsonCodec(), "a.json"), (PickleCodec(), "a.pkl")])
def test_codec_gives_the_extension(tmp_path: Path, codec: Codec, name: str) -> None:
    with FileStore(tmp_path, codec=codec) as store:
        store.set("a", {})
        assert file_names(store) == [name]


# --- keys and file names ---


def test_json_file_holds_json(store: FileStore) -> None:
    store.set("1", {"title": "a"})
    assert (store.path / "1.json").read_text(encoding="utf-8") == '{"title": "a"}'


def test_upper_case_key_is_escaped_in_the_file_name(store: FileStore) -> None:
    store.set("User:1", {})
    assert file_names(store) == ["%55ser%3A1.json"]


def test_keys_that_differ_by_case_are_two_files(store: FileStore) -> None:
    store.set("a", {"v": 1})
    store.set("A", {"v": 2})
    assert store.get_many(["a", "A"]) == [{"v": 1}, {"v": 2}]


@pytest.mark.parametrize("key", [".", "..", "../a", "/etc/passwd", "a\\b"])
def test_key_cannot_leave_the_directory(store: FileStore, key: str) -> None:
    store.set(key, {})
    assert [path.name for path in store.path.parent.iterdir()] == ["data"]


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("a" * 250, id="ascii"),
        pytest.param("A" * 83, id="upper"),
        pytest.param("é" * 41, id="accent"),
    ],
)
def test_longest_key(store: FileStore, key: str) -> None:
    store.set(key, {})
    assert list(store.keys()) == [key]


TOO_LONG_KEYS = [
    pytest.param("a" * 251, id="ascii"),
    pytest.param("A" * 84, id="upper"),
    pytest.param("é" * 42, id="accent"),
]


@pytest.mark.parametrize("key", TOO_LONG_KEYS)
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
def test_too_long_key_raises_and_changes_nothing(
    filled_store: FileStore, key: str, operation: Callable[[FileStore, str], Any]
) -> None:
    with pytest.raises(ValueError, match=r"The key is too long for FileStore"):
        operation(filled_store, key)
    assert file_names(filled_store) == ["1.json", "2.json", "3.json"]


def test_lone_surrogate_key_raises_and_writes_nothing(store: FileStore) -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        store.set_many({"a": {}, chr(0xD800): {}})
    assert file_names(store) == []


# --- open / close ---


def test__open_creates_missing_directories(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "nested" / "data")
    store._open()
    assert (tmp_path / "nested" / "data").is_dir()


def test__open_path_that_became_a_file(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "data")
    (tmp_path / "data").write_text("a")
    with pytest.raises(FileExistsError, match=r"data"):
        store.open()
    assert store.closed


def test__close_forgets_occupied_names(store: FileStore) -> None:
    store._shadowed = {"user.json"}
    store._close()
    assert store._shadowed == set()


def test_close_keeps_the_files(filled_store: FileStore) -> None:
    filled_store.close()
    assert file_names(filled_store) == ["1.json", "2.json", "3.json"]


def test_reopen_keeps_values(filled_store: FileStore) -> None:
    filled_store.close()
    filled_store.open()
    assert filled_store.count() == 3


# --- primitives ---


def test__get_many(filled_store: FileStore) -> None:
    assert filled_store._get_many(["3", "missing", "1", "3"]) == {
        "3": PAYLOADS["3"],
        "1": PAYLOADS["1"],
    }


def test__get_many_directory_is_a_missing_key(store: FileStore) -> None:
    (store.path / "a.json").mkdir()
    assert store._get_many(["a"]) == {}


def test__get_many_unreadable_file(
    filled_store: FileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(*_args: Any) -> None:
        msg = "not allowed"
        raise PermissionError(msg)

    monkeypatch.setattr("builtins.open", deny)
    with pytest.raises(PermissionError, match=r"not allowed"):
        filled_store._get_many(["1"])


@pytest.mark.parametrize("payload", ['{"é": 1}', '{"é": 1}'.encode()])
def test__put_many(store: FileStore, payload: str | bytes) -> None:
    store._put_many({"a": payload})
    assert (store.path / "a.json").read_bytes() == '{"é": 1}'.encode()


def test__put_many_replaces(filled_store: FileStore) -> None:
    filled_store._put_many({"1": "{}"})
    assert filled_store._get_many(["1"]) == {"1": b"{}"}


def test__update(filled_store: FileStore) -> None:
    filled_store._update(["1", "4"], lambda existing: {"4": existing["1"]})
    assert filled_store._get_many(["1", "4"]) == {"1": PAYLOADS["1"], "4": PAYLOADS["1"]}


def test__update_gives_the_existing_payloads_to_the_plan(filled_store: FileStore) -> None:
    received: list[dict] = []
    filled_store._update(["4", "1"], lambda existing: received.append(existing) or {})
    assert received == [{"1": PAYLOADS["1"]}]


def test__update_plan_raises_writes_nothing(filled_store: FileStore) -> None:
    plan = build_plan({"4": "{}", "1": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store._update(["4", "1"], plan)
    assert file_names(filled_store) == ["1.json", "2.json", "3.json"]


def test__delete_many(filled_store: FileStore) -> None:
    filled_store._delete_many(["1", "missing", "1", "3"])
    assert file_names(filled_store) == ["2.json"]


def test__clear(filled_store: FileStore) -> None:
    filled_store._clear()
    assert file_names(filled_store) == []


def test__clear_keeps_the_other_files(filled_store: FileStore) -> None:
    for name in ["User.json", "notes.txt", ".abc.tmp", "1.pkl"]:
        (filled_store.path / name).write_text("{}")
    (filled_store.path / "dir.json").mkdir()
    filled_store._clear()
    assert file_names(filled_store) == [".abc.tmp", "1.pkl", "User.json", "dir.json", "notes.txt"]


def test__count(filled_store: FileStore) -> None:
    assert filled_store._count() == 3


def test__count_ignores_the_other_files(store: FileStore) -> None:
    for name in ["User.json", "a b.json", "%c3%a9.json", "notes.txt", ".abc.tmp", "1.pkl"]:
        (store.path / name).write_text("{}")
    (store.path / "dir.json").mkdir()
    assert store._count() == 0


def test__contains_many(filled_store: FileStore) -> None:
    assert filled_store._contains_many(["1", "missing", "1", "3"]) == {"1", "3"}


@pytest.mark.parametrize(("batch_size", "sizes"), [(1, [1, 1, 1]), (2, [2, 1]), (3, [3])])
def test__iter_batches_sizes(filled_store: FileStore, batch_size: int, sizes: list[int]) -> None:
    assert [len(batch) for batch in filled_store._iter_batches(batch_size)] == sizes


def test__iter_batches_payloads(filled_store: FileStore) -> None:
    assert list(filled_store._iter_batches(10)) == [PAYLOADS]


def test__iter_batches_empty_store(store: FileStore) -> None:
    assert list(store._iter_batches(2)) == []


def test__iter_batches_skips_keys_deleted_since_the_snapshot(filled_store: FileStore) -> None:
    iterator = filled_store._iter_batches(1)
    first = next(iterator)
    filled_store._delete_many(["1", "2", "3"])
    assert (len(first), list(iterator)) == (1, [])


def test__iter_batches_does_not_yield_keys_written_after_the_snapshot(
    filled_store: FileStore,
) -> None:
    iterator = filled_store._iter_batches(1)
    visited = list(next(iterator))
    filled_store._put_many({"4": "{}"})
    visited.extend(key for batch in iterator for key in batch)
    assert sorted(visited) == ["1", "2", "3"]


@pytest.mark.parametrize(("batch_size", "sizes"), [(1, [1, 1, 1]), (2, [2, 1]), (3, [3])])
def test__iter_key_batches_sizes(
    filled_store: FileStore, batch_size: int, sizes: list[int]
) -> None:
    assert [len(batch) for batch in filled_store._iter_key_batches(batch_size)] == sizes


def test__iter_key_batches_does_not_read_the_files(
    filled_store: FileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_get_many", None)
    assert sorted(next(filled_store._iter_key_batches(10))) == ["1", "2", "3"]


def test__iter_key_batches_skips_keys_deleted_since_the_snapshot(
    filled_store: FileStore,
) -> None:
    iterator = filled_store._iter_key_batches(1)
    first = next(iterator)
    filled_store._delete_many(["1", "2", "3"])
    assert (len(first), list(iterator)) == (1, [])


# --- a file name occupied by another file ---


def test_occupied_name_is_a_missing_key(store: FileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    occupy_name(store, monkeypatch)
    assert store._get_many(["user"]) == {}


def test_occupied_name_is_not_contained(store: FileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    occupy_name(store, monkeypatch)
    assert store._contains_many(["user"]) == set()


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_write_of_occupied_name_raises_and_writes_nothing(
    store: FileStore, monkeypatch: pytest.MonkeyPatch, on_conflict: str
) -> None:
    occupy_name(store, monkeypatch)
    with pytest.raises(ValueError, match=r"cannot be written"):
        store.set_many({"other": {}, "user": {}}, on_conflict=on_conflict)
    assert file_names(store) == ["User.json"]


def test_delete_of_occupied_name_keeps_the_file(
    store: FileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    occupy_name(store, monkeypatch)
    store.delete("user")
    assert file_names(store) == ["User.json"]


@ignores_case
def test_open_finds_occupied_names(tmp_path: Path) -> None:
    (tmp_path / "User.json").write_text('{"old": true}')
    with FileStore(tmp_path) as store:
        assert store.get("user") is None


# --- uri ---


@pytest.mark.parametrize(
    ("codec", "scheme"), [(JsonCodec(), "file+json"), (PickleCodec(), "file+pickle")]
)
def test_to_uri(codec: Codec, scheme: str) -> None:
    assert FileStore("/data/a dir", codec=codec).to_uri() == f"{scheme}:/data/a%20dir"


@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec()])
def test_from_uri_gives_the_path_and_the_codec(tmp_path: Path, codec: Codec) -> None:
    restored = FileStore.from_uri(FileStore(tmp_path, codec=codec).to_uri())
    assert (restored.path, type(restored._codec)) == (tmp_path.resolve(), type(codec))


def test_from_uri_keeps_given_codec(tmp_path: Path) -> None:
    codec = PickleCodec()
    uri = FileStore(tmp_path, codec=codec).to_uri()
    assert FileStore.from_uri(uri, codec=codec)._codec is codec


def test_from_uri_ignores_read_only(tmp_path: Path) -> None:
    with FileStore.from_uri(FileStore(tmp_path).to_uri(), read_only=True) as store:
        store.set("a", {})
        assert store.contains("a")


def test_from_uri_unknown_option(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match=r"unexpected keyword argument"):
        FileStore.from_uri(FileStore(tmp_path).to_uri(), indent=2)


def test_from_uri_codec_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"does not match the scheme"):
        FileStore.from_uri(FileStore(tmp_path).to_uri(), codec=PickleCodec())


@pytest.mark.parametrize("uri", ["lmdb:/data", "file:/data", "/data"])
def test_from_uri_other_scheme(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid scheme"):
        FileStore.from_uri(uri)


# --- repr ---


def test_repr(filled_store: FileStore) -> None:
    assert repr(filled_store) == (
        f"FileStore(\n  (path): {filled_store.path}\n  (closed): False\n)"
    )


def test_repr_does_not_list_the_directory(
    filled_store: FileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(filled_store, "_list_keys", MagicMock(side_effect=AssertionError("scan")))
    assert "FileStore(" in repr(filled_store)


def test__get_repr_kwargs_closed(tmp_path: Path) -> None:
    assert FileStore(tmp_path)._get_repr_kwargs() == {
        "path": str(tmp_path.resolve()),
        "closed": True,
    }


def test__get_repr_kwargs_pickle_codec(tmp_path: Path) -> None:
    codec = PickleCodec()
    assert FileStore(tmp_path, codec=codec)._get_repr_kwargs()["codec"] is codec


# --- helpers of the instance ---


def test__file_names(store: FileStore) -> None:
    assert store._file_names(["b", "A", "b"]) == {"b": "b.json", "A": "%41.json"}


def test__list_keys(filled_store: FileStore) -> None:
    filled_store.set("A/b", {})
    assert sorted(filled_store._list_keys()) == ["1", "2", "3", "A/b"]


@pytest.mark.parametrize(("name", "expected"), [("1.json", True), ("4.json", False)])
def test__is_file_of_key(filled_store: FileStore, name: str, expected: bool) -> None:
    assert filled_store._is_file_of_key(name) is expected


def test__is_file_of_key_occupied_name(store: FileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    occupy_name(store, monkeypatch)
    monkeypatch.setattr("os.path.isfile", lambda _path: True)
    assert not store._is_file_of_key("user.json")


def test__is_shadowed(store: FileStore, monkeypatch: pytest.MonkeyPatch) -> None:
    occupy_name(store, monkeypatch)
    assert store._is_shadowed("user.json")


def test__is_shadowed_unknown_name(filled_store: FileStore) -> None:
    assert not filled_store._is_shadowed("1.json")


def test__is_shadowed_once_the_other_file_is_removed(store: FileStore) -> None:
    store._shadowed = {"user.json"}
    assert not store._is_shadowed("user.json")


def test__is_shadowed_name_that_exists(filled_store: FileStore) -> None:
    filled_store._shadowed = {"1.json"}
    assert not filled_store._is_shadowed("1.json")


def test__check_not_shadowed(filled_store: FileStore) -> None:
    assert filled_store._check_not_shadowed({"1": "1.json"}) is None


def test__check_not_shadowed_occupied_name(
    store: FileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    occupy_name(store, monkeypatch)
    with pytest.raises(ValueError, match=r"The key 'user' cannot be written"):
        store._check_not_shadowed({"a": "a.json", "user": "user.json"})


#######################################
#     Tests for _encode_file_name     #
#######################################


@pytest.mark.parametrize(
    ("key", "name"),
    [
        ("", ".json"),
        ("abc-1_.~", "abc-1_.~.json"),
        ("User:1", "%55ser%3A1.json"),
        ("AZ", "%41%5A.json"),
        ("a b/c", "a%20b%2Fc.json"),
        ("%41", "%2541.json"),
        ("é", "%C3%A9.json"),
        ("É", "%C3%89.json"),
        ("..", "...json"),
    ],
)
def test__encode_file_name(key: str, name: str) -> None:
    assert _encode_file_name(key, ".json") == name


def test__encode_file_name_names_differ_when_case_is_ignored() -> None:
    keys = ["a", "A", "%41", "%61", "aA", "Aa", ":", "%3a", "%3A", "é", "É", "%c3%a9"]
    names = {_encode_file_name(key, ".json").lower() for key in keys}
    assert len(names) == len(keys)


def test__encode_file_name_longest() -> None:
    assert len(_encode_file_name("a" * 250, ".json")) == 255


def test__encode_file_name_too_long() -> None:
    with pytest.raises(ValueError, match=r"would have 256 characters, more than 255"):
        _encode_file_name("a" * 251, ".json")


def test__encode_file_name_lone_surrogate() -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        _encode_file_name(chr(0xD800), ".json")


###################################
#     Tests for _escape_upper     #
###################################


@pytest.mark.parametrize(("text", "expected"), [("U", "%55"), ("%3A", "%3A")])
def test__escape_upper(text: str, expected: str) -> None:
    assert _escape_upper(_ESCAPE_OR_UPPER.match(text)) == expected


#######################################
#     Tests for _decode_file_name     #
#######################################


@pytest.mark.parametrize("key", ["", "a", "User:1", "a b/c", "é", "%41", ".."])
def test__decode_file_name(key: str) -> None:
    assert _decode_file_name(_encode_file_name(key, ".json"), ".json") == key


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("a.pkl", id="other_extension"),
        pytest.param("User.json", id="upper_case"),
        pytest.param("%c3%a9.json", id="lower_case_escape"),
        pytest.param("a b.json", id="not_escaped"),
        pytest.param("%61.json", id="needless_escape"),
        pytest.param("%FF.json", id="not_utf8"),
        pytest.param("a" * 251 + ".json", id="too_long"),
    ],
)
def test__decode_file_name_not_a_key(name: str) -> None:
    assert _decode_file_name(name, ".json") is None


##########################################
#     Tests for _find_shadowed_names     #
##########################################


@ignores_case
@pytest.mark.parametrize(
    ("name", "occupied"),
    [("User.json", "user.json"), ("A%3Ab.json", "a%3Ab.json"), ("%C3%A9A.json", "%C3%A9a.json")],
)
def test__find_shadowed_names(tmp_path: Path, name: str, occupied: str) -> None:
    (tmp_path / name).write_text("{}")
    assert _find_shadowed_names(tmp_path, ".json") == {occupied}


def test__find_shadowed_names_file_system_that_ignores_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "User.json").write_text("{}")
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    assert _find_shadowed_names(tmp_path, ".json") == {"user.json"}


@pytest.mark.parametrize(
    "names",
    [
        pytest.param([], id="empty"),
        pytest.param(["user.json", "%55ser.json"], id="key_files"),
        pytest.param(["User.txt"], id="other_extension"),
        pytest.param(["%c3%a9.json"], id="no_upper_case_letter"),
        pytest.param(["A B.json"], id="no_key_in_another_case"),
        pytest.param(["A" + "é" * 50 + ".json"], id="too_long"),
    ],
)
def test__find_shadowed_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: list[str]
) -> None:
    for name in names:
        (tmp_path / name).write_text("{}")
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    assert _find_shadowed_names(tmp_path, ".json") == set()


def test__find_shadowed_names_name_of_another_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file system that keeps both names: the key file is not occupied.
    monkeypatch.setattr("os.listdir", lambda _path: ["User.json", "user.json"])
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    assert _find_shadowed_names(tmp_path, ".json") == set()


#################################
#     Tests for _write_file     #
#################################


@pytest.mark.parametrize("payload", ["é", "é".encode()])
def test__write_file(tmp_path: Path, payload: str | bytes) -> None:
    _write_file(tmp_path / "a", payload)
    assert (tmp_path / "a").read_bytes() == "é".encode()


def test__write_file_leaves_no_temporary_file(tmp_path: Path) -> None:
    _write_file(tmp_path / "a", b"1")
    assert list_directory(tmp_path) == ["a"]


def test__write_file_uses_the_default_permissions(tmp_path: Path) -> None:
    (tmp_path / "reference").write_bytes(b"")
    _write_file(tmp_path / "a", b"1")
    assert (tmp_path / "a").stat().st_mode == (tmp_path / "reference").stat().st_mode


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test__write_file_failure_keeps_the_old_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    (tmp_path / "a").write_bytes(b"old")

    def fail(*_args: Any) -> None:
        msg = "cannot rename"
        raise error(msg)

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(error, match=r"cannot rename"):
        _write_file(tmp_path / "a", b"new")
    assert ((tmp_path / "a").read_bytes(), list_directory(tmp_path)) == (b"old", ["a"])
