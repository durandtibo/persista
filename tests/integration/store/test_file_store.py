r"""Tests of ``FileStore`` on the real file system, for the behaviours
that the unit tests simulate, and for its concurrency guarantees."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from persista.store import FileStore

NUM_THREADS = 8
NUM_WRITES = 50


def ignores_case_file_system() -> bool:
    r"""Indicate whether the file system of the temporary directory
    ignores the case of the file names."""
    with tempfile.TemporaryDirectory() as path:
        (Path(path) / "a").touch()
        return (Path(path) / "A").exists()


ignores_case = pytest.mark.skipif(
    not ignores_case_file_system(), reason="Requires a file system that ignores case"
)
respects_case = pytest.mark.skipif(
    ignores_case_file_system(), reason="Requires a file system that respects case"
)


def file_names(path: Path) -> list[str]:
    r"""Return the sorted names of the files of a directory."""
    return sorted(file.name for file in path.iterdir())


#####################################
#     Files of earlier versions     #
#####################################


def test_file_of_earlier_version_with_lower_case_key_is_read(tmp_path: Path) -> None:
    r"""Test that the file of a key without upper-case letter, as an
    earlier version named it, is read."""
    (tmp_path / "user%3A%C3%89.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        assert store.get("user:É") == {"v": 1}


def test_file_of_earlier_version_with_upper_case_key_is_not_listed(tmp_path: Path) -> None:
    r"""Test that the file of a key with an upper-case letter, as an
    earlier version named it, is not a key of the store."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        assert (list(store.keys()), store.count(), store.get("User")) == ([], 0, None)


def test_clear_keeps_the_file_of_earlier_version(tmp_path: Path) -> None:
    r"""Test that ``clear`` does not delete a file that is not a key of
    the store."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        store.set("a", {})
        store.clear()
    assert file_names(tmp_path) == ["User.json"]


@ignores_case
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.get("user"), id="get"),
        pytest.param(lambda s: s.contains("user") or None, id="contains"),
        pytest.param(lambda s: s.delete("user"), id="delete"),
    ],
)
def test_other_case_file_is_not_the_value_of_a_key(tmp_path: Path, operation: object) -> None:
    r"""Test that a file that differs from the name of a key only by
    case is neither read nor deleted."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        result = operation(store)
    assert (result, file_names(tmp_path)) == (None, ["User.json"])


@ignores_case
def test_write_over_other_case_file_raises(tmp_path: Path) -> None:
    r"""Test that a write does not replace a file that differs from the
    name of the key only by case."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        with pytest.raises(ValueError, match=r"cannot be written"):
            store.set("user", {"v": 2})
        assert (tmp_path / "User.json").read_text() == '{"v": 1}'


@ignores_case
def test_key_can_be_written_once_the_other_case_file_is_removed(tmp_path: Path) -> None:
    r"""Test that a key can be written once the file that occupied its
    name is removed, without reopening the store."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        (tmp_path / "User.json").unlink()
        store.set("user", {"v": 2})
        assert list(store.keys()) == ["user"]


@respects_case
def test_other_case_file_does_not_occupy_a_name(tmp_path: Path) -> None:
    r"""Test that, on a file system that respects case, a file of an
    earlier version does not prevent a write."""
    (tmp_path / "User.json").write_text('{"v": 1}')
    with FileStore(tmp_path) as store:
        store.set("user", {"v": 2})
        assert store.get("user") == {"v": 2}


#######################
#     File system     #
#######################


def test_longest_key_is_accepted_by_the_file_system(tmp_path: Path) -> None:
    r"""Test that the file system accepts the longest file name of the
    store."""
    with FileStore(tmp_path) as store:
        store.set("a" * 250, {"v": 1})
        assert store.get("a" * 250) == {"v": 1}


def test_failed_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    r"""Test that a write that cannot replace its target, here a
    directory, removes its temporary file."""
    (tmp_path / "a.json").mkdir()
    with FileStore(tmp_path) as store, pytest.raises(OSError, match=r"a\.json"):
        store.set("a", {})
    assert file_names(tmp_path) == ["a.json"]


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="Requires file permissions"
)
def test_unreadable_file_raises(tmp_path: Path) -> None:
    r"""Test that a file that cannot be read is not reported as a
    missing key."""
    with FileStore(tmp_path) as store:
        store.set("a", {})
        (tmp_path / "a.json").chmod(0)
        with pytest.raises(PermissionError, match=r"a\.json"):
            store.get("a")


#######################
#     Concurrency     #
#######################


def test_reader_never_sees_a_partial_value(tmp_path: Path) -> None:
    r"""Test that a store that reads while another instance writes only
    sees complete values."""
    values = [{"v": "a" * 100_000}, {"v": "b" * 50_000}]
    stop = threading.Event()
    seen: list[bool] = []
    lock = threading.Lock()
    with FileStore(tmp_path) as writer, FileStore(tmp_path) as reader:
        writer.set("a", values[0])

        def read() -> None:
            while not stop.is_set():
                complete = reader.get("a") in values
                with lock:
                    seen.append(complete)

        thread = threading.Thread(target=read)
        thread.start()
        for i in range(NUM_WRITES * 4):
            writer.set("a", values[i % 2])
        stop.set()
        thread.join()
    assert set(seen) <= {True}


async def test_merge_does_not_lose_updates_of_set_and_aset(tmp_path: Path) -> None:
    r"""Test that merges of one instance from threads and from tasks
    keep every field."""
    with FileStore(tmp_path) as store:

        def write(thread: int) -> None:
            for i in range(NUM_WRITES):
                store.set("a", {f"sync-{thread}-{i}": i}, on_conflict="merge")

        await asyncio.gather(
            *(asyncio.to_thread(write, thread) for thread in range(NUM_THREADS)),
            *(store.aset("a", {f"async-{i}": i}, on_conflict="merge") for i in range(NUM_WRITES)),
        )
        assert len(store.get("a")) == (NUM_THREADS + 1) * NUM_WRITES


def test_two_instances_can_write_the_same_key(tmp_path: Path) -> None:
    r"""Test that two instances that write one key at the same time
    leave a complete value and no temporary file."""
    with FileStore(tmp_path) as first, FileStore(tmp_path) as second:

        def write(store: FileStore) -> None:
            for i in range(NUM_WRITES):
                store.set("a", {"v": i})

        threads = [threading.Thread(target=write, args=(store,)) for store in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert (first.get("a"), file_names(tmp_path)) == ({"v": NUM_WRITES - 1}, ["a.json"])
