from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import pytest

from persista.store import JsonCodec, PickleCodec
from persista.store.uri import (
    codec_uri_scheme,
    decode_codec_uri,
    decode_path_uri,
    encode_path_uri,
    split_uri,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from persista.store import Codec

SCHEMES = {"json": "file+json", "pickle": "file+pickle"}


class CustomJsonCodec(JsonCodec):
    r"""A codec of the same name as ``JsonCodec``."""


class OtherCodec(JsonCodec):
    r"""A codec with a name that no URI scheme has."""

    name = "other"


def test_encode_decode_round_trip_absolute_path() -> None:
    uri = encode_path_uri("sqlite", "/data/foo/bar.db")
    assert decode_path_uri(uri, expected_scheme="sqlite") == "/data/foo/bar.db"


def test_encode_decode_round_trip_memory_sentinel() -> None:
    uri = encode_path_uri("sqlite", ":memory:")
    assert decode_path_uri(uri, expected_scheme="sqlite") == ":memory:"


def test_encode_decode_round_trip_relative_path() -> None:
    uri = encode_path_uri("lmdb", "relative/dir")
    assert decode_path_uri(uri, expected_scheme="lmdb") == "relative/dir"


def test_encode_uses_expected_scheme() -> None:
    uri = encode_path_uri("file+json", "/data/store")
    assert uri.startswith("file+json:")


def test_decode_rejects_wrong_scheme() -> None:
    uri = encode_path_uri("sqlite", "/data/foo.db")
    with pytest.raises(ValueError, match="scheme"):
        decode_path_uri(uri, expected_scheme="duckdb")


def test_encode_decode_round_trip_path_with_special_chars() -> None:
    uri = encode_path_uri("file+pickle", "/data/a dir/with?special#chars.db")
    assert (
        decode_path_uri(uri, expected_scheme="file+pickle") == "/data/a dir/with?special#chars.db"
    )


######################################
#     Tests for codec_uri_scheme     #
######################################


@pytest.mark.parametrize(
    ("codec", "scheme"), [(JsonCodec(), "file+json"), (PickleCodec(), "file+pickle")]
)
def test_codec_uri_scheme(codec: Codec, scheme: str) -> None:
    assert codec_uri_scheme(codec, SCHEMES) == scheme


def test_codec_uri_scheme_unsupported_codec() -> None:
    with pytest.raises(ValueError, match=r"needs a codec named \['json', 'pickle'\], not 'other'"):
        codec_uri_scheme(OtherCodec(), SCHEMES)


######################################
#     Tests for decode_codec_uri     #
######################################


@pytest.mark.parametrize(
    ("uri", "codec_type"),
    [("file+json:/data/a%20b", JsonCodec), ("file+pickle:/data/a%20b", PickleCodec)],
)
def test_decode_codec_uri(uri: str, codec_type: type) -> None:
    location, codec = decode_codec_uri(uri, schemes=SCHEMES)
    assert (location, type(codec)) == ("/data/a b", codec_type)


def test_decode_codec_uri_keeps_given_codec() -> None:
    codec = CustomJsonCodec()
    assert decode_codec_uri("file+json:data", schemes=SCHEMES, codec=codec)[1] is codec


@pytest.mark.parametrize("uri", ["file:data", "lmdb:data", "data", ""])
def test_decode_codec_uri_other_scheme(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid scheme of the URI: expected one of"):
        decode_codec_uri(uri, schemes=SCHEMES)


@pytest.mark.parametrize(
    ("uri", "codec"),
    [("file+json:data", PickleCodec()), ("file+pickle:data", JsonCodec())],
)
def test_decode_codec_uri_codec_mismatch(uri: str, codec: Codec) -> None:
    with pytest.raises(ValueError, match=r"does not match the scheme"):
        decode_codec_uri(uri, schemes=SCHEMES, codec=codec)


###############################
#     Tests for split_uri     #
###############################


def test_split_uri() -> None:
    parts = split_uri("redis://localhost:6379/0")
    assert (parts.scheme, parts.netloc, parts.path) == ("redis", "localhost:6379", "/0")


@pytest.mark.parametrize(
    "uri",
    [
        "redis://user:s3cret@[bad",
        # A character that NFKC normalization turns into "a/c".
        f"redis://user:s3cret@ho{chr(0x2100)}st",
    ],
)
def test_split_uri_invalid_uri_is_not_quoted(uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid URI: it cannot be parsed") as info:
        split_uri(uri)
    assert "s3cret" not in "".join(traceback.format_exception(info.value))


@pytest.mark.parametrize(
    "decode",
    [
        pytest.param(lambda uri: decode_path_uri(uri, expected_scheme="sqlite"), id="path"),
        pytest.param(lambda uri: decode_codec_uri(uri, schemes=SCHEMES), id="codec"),
    ],
)
@pytest.mark.parametrize(
    "uri",
    [
        "redis://user:s3cret@localhost",
        "host=localhost password=s3cret",
        "user:s3cret@localhost",
        f"redis://user:s3cret@ho{chr(0x2100)}st",
    ],
)
def test_decode_uri_error_hides_the_password(decode: Callable[[str], object], uri: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid (scheme of the URI|URI)") as info:
        decode(uri)
    assert "s3cret" not in "".join(traceback.format_exception(info.value))


def test_decode_codec_uri_mismatch_does_not_quote_the_uri() -> None:
    with pytest.raises(
        ValueError, match=r"does not match the scheme 'file\+json' of the URI"
    ) as info:
        decode_codec_uri("file+json:/s3cret", schemes=SCHEMES, codec=PickleCodec())
    assert "s3cret" not in str(info.value)
