from __future__ import annotations

import pytest

from persista.store.uri import decode_path_uri, encode_path_uri


def test_encode_decode_round_trip_absolute_path() -> None:
    uri = encode_path_uri("sqlite", "/tmp/foo/bar.db")
    assert decode_path_uri(uri, expected_scheme="sqlite") == "/tmp/foo/bar.db"


def test_encode_decode_round_trip_memory_sentinel() -> None:
    uri = encode_path_uri("sqlite", ":memory:")
    assert decode_path_uri(uri, expected_scheme="sqlite") == ":memory:"


def test_encode_decode_round_trip_relative_path() -> None:
    uri = encode_path_uri("lmdb", "relative/dir")
    assert decode_path_uri(uri, expected_scheme="lmdb") == "relative/dir"


def test_encode_uses_expected_scheme() -> None:
    uri = encode_path_uri("file+json", "/tmp/data")
    assert uri.startswith("file+json:")


def test_decode_rejects_wrong_scheme() -> None:
    uri = encode_path_uri("sqlite", "/tmp/foo.db")
    with pytest.raises(ValueError, match="scheme"):
        decode_path_uri(uri, expected_scheme="duckdb")


def test_encode_decode_round_trip_path_with_special_chars() -> None:
    uri = encode_path_uri("file+pickle", "/tmp/a dir/with?special#chars.db")
    assert decode_path_uri(uri, expected_scheme="file+pickle") == "/tmp/a dir/with?special#chars.db"
