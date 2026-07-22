from __future__ import annotations

from pathlib import Path

from persista.utils.path import prepare_store_path

#########################################
#     Tests for prepare_store_path     #
#########################################


def test_prepare_store_path_in_memory_returns_unchanged() -> None:
    assert prepare_store_path(":memory:") == ":memory:"


def test_prepare_store_path_creates_missing_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dirs" / "db.duckdb"
    assert not target.parent.exists()

    result = prepare_store_path(target)

    assert target.parent.is_dir()
    assert result == target


def test_prepare_store_path_creates_deeply_nested_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c" / "d" / "db.duckdb"

    result = prepare_store_path(target)

    assert target.parent.is_dir()
    assert result == target


def test_prepare_store_path_existing_parent_directory_is_noop(tmp_path: Path) -> None:
    target = tmp_path / "db.duckdb"
    assert tmp_path.is_dir()  # tmp_path fixture already creates this

    result = prepare_store_path(target)

    assert target.parent == tmp_path
    assert result == target


def test_prepare_store_path_does_not_create_the_file_itself(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "db.duckdb"

    prepare_store_path(target)

    assert target.parent.is_dir()
    assert not target.exists()


def test_prepare_store_path_accepts_str_input(tmp_path: Path) -> None:
    target_str = str(tmp_path / "sub" / "db.duckdb")

    result = prepare_store_path(target_str)

    assert Path(target_str).parent.is_dir()
    assert Path(result) == Path(target_str)


def test_prepare_store_path_returns_path_instance_for_file_paths(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "db.duckdb"
    result = prepare_store_path(target)

    assert isinstance(result, Path)


def test_prepare_store_path_idempotent_when_called_twice(tmp_path: Path) -> None:
    """Calling twice on the same path should not raise even though the
    directory already exists after the first call."""
    target = tmp_path / "sub" / "db.duckdb"

    first = prepare_store_path(target)
    second = prepare_store_path(target)

    assert first == second
    assert target.parent.is_dir()
