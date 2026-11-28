from __future__ import annotations

import gzip
import io
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from persista.cache import Cache
from persista.http.httpx.client import (
    AsyncHttpClient,
    HttpClient,
    _cache_key,
    _check_client_is_open,
    _entry_to_response,
    _is_replayable_body,
    _is_transient_error,
    _plan_retry,
    _prepare_cache_lookup,
    _response_to_entry,
)
from persista.http.retry import IDEMPOTENT_METHODS, RetryPolicy
from persista.utils.canonical import hash_canonical

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

httpx = pytest.importorskip("httpx")


MODULE = "persista.http.httpx.client"


@pytest.fixture(autouse=True)
def sleep(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace the sync and async sleeps, and record the delays."""
    mock = Mock()

    async def fake_async_sleep(delay: float) -> None:
        mock(delay)

    monkeypatch.setattr(f"{MODULE}.time.sleep", mock)
    monkeypatch.setattr(f"{MODULE}.asyncio.sleep", fake_async_sleep)
    return mock


def _counting_handler(json_factory: Callable[[int], dict[str, object]]) -> tuple[Callable, Mock]:
    calls = Mock(side_effect=range(1_000_000))

    def handler(request: httpx.Request) -> httpx.Response:
        n = calls()
        return httpx.Response(200, json=json_factory(n), request=request)

    return handler, calls


def _client(handler: Callable) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _async_client(handler: Callable) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _cache() -> Cache:
    cache = Cache()
    cache.open()
    return cache


############################
#       HttpClient        #
############################


def test_http_client_no_cache_by_default() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    assert client.get("https://example.com").json() == {"n": 0}
    assert client.get("https://example.com").json() == {"n": 1}
    assert calls.call_count == 2


def test_http_client_caches_get_on_hit() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    r1 = client.get("https://example.com/foo")
    r2 = client.get("https://example.com/foo")

    assert r1.json() == r2.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_cache_keys_differ_by_url() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com/foo")
    client.get("https://example.com/bar")

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_params() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com", params={"x": 1})
    client.get("https://example.com", params={"x": 2})

    assert calls.call_count == 2


def test_http_client_put() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.put("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_patch() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.patch("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_delete() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(client=_client(handler))

    response = client.delete("https://example.com")

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


def test_http_client_does_not_cache_non_cacheable_method() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.post("https://example.com", json={"a": 1})
    client.post("https://example.com", json={"a": 1})

    assert calls.call_count == 2


def test_http_client_does_not_cache_error_response() -> None:
    calls = Mock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        calls()
        return httpx.Response(500, request=request)

    client = HttpClient(cache=_cache(), max_retries=0, client=_client(handler))

    with pytest.raises(httpx.HTTPStatusError, match=r"500 Internal Server Error"):
        client.get("https://example.com")
    with pytest.raises(httpx.HTTPStatusError, match=r"500 Internal Server Error"):
        client.get("https://example.com")

    assert calls.call_count == 2


############################
#     AsyncHttpClient     #
############################


async def test_async_http_client_caches_get_on_hit() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))

    r1 = await client.get("https://example.com/foo")
    r2 = await client.get("https://example.com/foo")

    assert r1.json() == r2.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_no_cache_by_default() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    await client.get("https://example.com")
    await client.get("https://example.com")

    assert calls.call_count == 2


async def test_async_http_client_post() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.post("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_put() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.put("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_patch() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.patch("https://example.com", json={"a": 1})

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


async def test_async_http_client_delete() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(client=_async_client(handler))

    response = await client.delete("https://example.com")

    assert response.json() == {"n": 0}
    assert calls.call_count == 1


########################################
#     Tests for HttpClient caching     #
########################################


def test_http_client_cache_keys_differ_by_client_headers() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    cache = _cache()
    alice = HttpClient(
        cache=cache,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer alice"}
        ),
    )
    bob = HttpClient(
        cache=cache,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer bob"}
        ),
    )

    alice.get("https://example.com")

    assert bob.get("https://example.com").json() == {"n": 1}


def test_http_client_cache_keys_differ_by_call_headers() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com", headers={"X-User": "alice"})
    client.get("https://example.com", headers={"X-User": "bob"})

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_client_cookies() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    httpx_client = _client(handler)
    client = HttpClient(cache=_cache(), client=httpx_client)

    httpx_client.cookies.set("session", "alice")
    client.get("https://example.com")
    httpx_client.cookies.set("session", "bob")
    client.get("https://example.com")

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_call_cookies() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    with pytest.warns(DeprecationWarning, match=r"per-request cookies"):
        client.get("https://example.com", cookies={"session": "alice"})
    with pytest.warns(DeprecationWarning, match=r"per-request cookies"):
        client.get("https://example.com", cookies={"session": "bob"})

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_base_url() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    cache = _cache()
    first = HttpClient(
        cache=cache,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://a.example.com"
        ),
    )
    second = HttpClient(
        cache=cache,
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url="https://b.example.com"
        ),
    )

    first.get("/items")

    assert second.get("/items").json() == {"n": 1}


def test_http_client_cache_keys_differ_by_client_params() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    httpx_client = _client(handler)
    client = HttpClient(cache=_cache(), client=httpx_client)

    httpx_client.params = {"user": "alice"}
    client.get("https://example.com")
    httpx_client.params = {"user": "bob"}
    client.get("https://example.com")

    assert calls.call_count == 2


def test_http_client_cache_keys_differ_by_query_params_object() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com", params=httpx.QueryParams({"p": 1}))

    assert client.get("https://example.com", params=httpx.QueryParams({"p": 2})).json() == {"n": 1}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param({"content": b"a"}, {"content": b"b"}, id="bytes"),
        pytest.param({"json": {"a": 1}}, {"json": {"a": 2}}, id="json"),
        pytest.param({"data": {"a": "1"}}, {"data": {"a": "2"}}, id="form"),
    ],
)
def test_http_client_cache_keys_differ_by_body(
    first: dict[str, Any], second: dict[str, Any]
) -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), cacheable_methods={"POST"}, client=_client(handler))

    client.post("https://example.com", **first)
    client.post("https://example.com", **second)

    assert calls.call_count == 2


def test_http_client_caches_same_body() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), cacheable_methods={"POST"}, client=_client(handler))

    client.post("https://example.com", content=b"a")
    client.post("https://example.com", content=b"a")

    assert calls.call_count == 1


def test_http_client_does_not_cache_with_client_auth() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(
        cache=_cache(),
        client=httpx.Client(transport=httpx.MockTransport(handler), auth=("alice", "secret")),
    )

    client.get("https://example.com")
    client.get("https://example.com")

    assert calls.call_count == 2


def test_http_client_does_not_cache_with_call_auth() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com", auth=("alice", "secret"))
    client.get("https://example.com", auth=("alice", "secret"))

    assert calls.call_count == 2


def test_http_client_call_auth_does_not_read_cache() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com")

    assert client.get("https://example.com", auth=("alice", "secret")).json() == {"n": 1}


def test_http_client_does_not_cache_streaming_body() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), cacheable_methods={"POST"}, client=_client(handler))

    client.post("https://example.com", content=iter([b"a"]))
    client.post("https://example.com", content=iter([b"a"]))

    assert calls.call_count == 2


def test_http_client_sends_streaming_body_unconsumed() -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        return httpx.Response(200)

    client = HttpClient(cache=_cache(), cacheable_methods={"POST"}, client=_client(handler))

    client.post("https://example.com", content=iter([b"a", b"b"]))

    assert bodies == [b"ab"]


def test_http_client_caches_empty_response() -> None:
    calls = Mock(return_value=None)

    def handler(_request: httpx.Request) -> httpx.Response:
        calls()
        return httpx.Response(200)

    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com")
    client.get("https://example.com")

    assert calls.call_count == 1


def test_http_client_cache_hit_gzip_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=gzip.compress(b'{"n": 0}')
        )

    client = HttpClient(cache=_cache(), client=_client(handler))
    client.get("https://example.com")

    assert client.get("https://example.com").json() == {"n": 0}


def test_http_client_cache_hit_raise_for_status() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))
    client.get("https://example.com")

    response = client.get("https://example.com")

    assert response.raise_for_status() is response


def test_http_client_cache_hit_has_request() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = HttpClient(cache=_cache(), client=_client(handler))
    client.get("https://example.com/foo")

    assert str(client.get("https://example.com/foo").request.url) == "https://example.com/foo"


def test_http_client_cache_sends_one_shot_headers() -> None:
    values = []

    def handler(request: httpx.Request) -> httpx.Response:
        values.append(request.headers.get("x-user"))
        return httpx.Response(200)

    client = HttpClient(cache=_cache(), client=_client(handler))

    client.get("https://example.com", headers=zip(["x-user"], ["alice"], strict=True))

    assert values == ["alice"]


#############################################
#     Tests for AsyncHttpClient caching     #
#############################################


async def test_async_http_client_cache_keys_differ_by_client_headers() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    cache = _cache()
    alice = AsyncHttpClient(
        cache=cache,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer alice"}
        ),
    )
    bob = AsyncHttpClient(
        cache=cache,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer bob"}
        ),
    )

    await alice.get("https://example.com")

    assert (await bob.get("https://example.com")).json() == {"n": 1}


async def test_async_http_client_cache_keys_differ_by_base_url() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    cache = _cache()
    first = AsyncHttpClient(
        cache=cache,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://a.example.com"
        ),
    )
    second = AsyncHttpClient(
        cache=cache,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://b.example.com"
        ),
    )

    await first.get("/items")

    assert (await second.get("/items")).json() == {"n": 1}


async def test_async_http_client_cache_keys_differ_by_query_params_object() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))

    await client.get("https://example.com", params=httpx.QueryParams({"p": 1}))
    response = await client.get("https://example.com", params=httpx.QueryParams({"p": 2}))

    assert response.json() == {"n": 1}


async def test_async_http_client_cache_keys_differ_by_body() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(
        cache=_cache(), cacheable_methods={"POST"}, client=_async_client(handler)
    )

    await client.post("https://example.com", content=b"a")
    await client.post("https://example.com", content=b"b")

    assert calls.call_count == 2


async def test_async_http_client_does_not_cache_with_client_auth() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(
        cache=_cache(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=("alice", "secret")),
    )

    await client.get("https://example.com")
    await client.get("https://example.com")

    assert calls.call_count == 2


async def test_async_http_client_does_not_cache_with_call_auth() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))

    await client.get("https://example.com", auth=("alice", "secret"))
    await client.get("https://example.com", auth=("alice", "secret"))

    assert calls.call_count == 2


async def test_async_http_client_does_not_cache_streaming_body() -> None:
    handler, calls = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(
        cache=_cache(), cacheable_methods={"POST"}, client=_async_client(handler)
    )

    async def body() -> AsyncIterator[bytes]:
        yield b"a"

    await client.post("https://example.com", content=body())
    await client.post("https://example.com", content=body())

    assert calls.call_count == 2


async def test_async_http_client_cache_hit_gzip_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=gzip.compress(b'{"n": 0}')
        )

    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))
    await client.get("https://example.com")

    assert (await client.get("https://example.com")).json() == {"n": 0}


async def test_async_http_client_cache_hit_raise_for_status() -> None:
    handler, _ = _counting_handler(lambda n: {"n": n})
    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))
    await client.get("https://example.com")

    response = await client.get("https://example.com")

    assert response.raise_for_status() is response


async def test_async_http_client_cache_sends_one_shot_headers() -> None:
    values = []

    def handler(request: httpx.Request) -> httpx.Response:
        values.append(request.headers.get("x-user"))
        return httpx.Response(200)

    client = AsyncHttpClient(cache=_cache(), client=_async_client(handler))

    await client.get("https://example.com", headers=zip(["x-user"], ["alice"], strict=True))

    assert values == ["alice"]


###########################################
#     Tests for _prepare_cache_lookup     #
###########################################


def _lookup(
    client: httpx.Client | None = None, url: str = "https://example.com", **kwargs: Any
) -> tuple[httpx.Request, str] | None:
    return _prepare_cache_lookup(client or httpx.Client(), "GET", url, kwargs)


def _lookup_key(client: httpx.Client | None = None, **kwargs: Any) -> str:
    """Return the cache key of a call that can be cached."""
    _, key = _lookup(client, **kwargs)
    return key


def test_prepare_cache_lookup_returns_request_of_client() -> None:
    request, _ = _lookup(
        httpx.Client(base_url="https://example.com/api", params={"a": "1"}), url="/items"
    )

    assert str(request.url) == "https://example.com/api/items?a=1"


def test_prepare_cache_lookup_returns_key_of_request() -> None:
    request, key = _lookup()

    assert key == _cache_key(request, follow_redirects=False)


def test_prepare_cache_lookup_deterministic() -> None:
    assert _lookup_key(headers={"x": "1"}) == _lookup_key(headers={"x": "1"})


def test_prepare_cache_lookup_async_client() -> None:
    assert _prepare_cache_lookup(httpx.AsyncClient(), "GET", "https://example.com", {}) is not None


def test_prepare_cache_lookup_does_not_mutate_kwargs() -> None:
    kwargs = {"auth": None, "follow_redirects": True, "params": {"a": 1}}

    _prepare_cache_lookup(httpx.Client(), "GET", "https://example.com", kwargs)

    assert kwargs == {"auth": None, "follow_redirects": True, "params": {"a": 1}}


def test_prepare_cache_lookup_client_auth() -> None:
    assert _lookup(httpx.Client(auth=("alice", "secret"))) is None


def test_prepare_cache_lookup_call_auth() -> None:
    assert _lookup(auth=("alice", "secret")) is None


def test_prepare_cache_lookup_call_use_client_default_auth() -> None:
    client = httpx.Client(auth=("alice", "secret"))

    assert _lookup(client, auth=httpx.USE_CLIENT_DEFAULT) is None


def test_prepare_cache_lookup_call_disables_client_auth() -> None:
    assert _lookup(httpx.Client(auth=("alice", "secret")), auth=None) is not None


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://alice:secret@example.com", id="username-and-password"),
        pytest.param("https://token@example.com", id="username"),
    ],
)
def test_prepare_cache_lookup_url_credentials(url: str) -> None:
    assert _lookup(url=url) is None


def test_prepare_cache_lookup_base_url_credentials() -> None:
    client = httpx.Client(base_url="https://alice:secret@example.com")

    assert _lookup(client, url="/items") is None


def test_prepare_cache_lookup_request_event_hook() -> None:
    client = httpx.Client(event_hooks={"request": [lambda _request: None]})

    assert _lookup(client) is None


def test_prepare_cache_lookup_response_event_hook() -> None:
    client = httpx.Client(event_hooks={"response": [lambda _response: None]})

    assert _lookup(client) is not None


def test_prepare_cache_lookup_extensions() -> None:
    assert _lookup(extensions={"sni_hostname": "other.example.com"}) is None


def test_prepare_cache_lookup_empty_extensions() -> None:
    assert _lookup(extensions={}) is not None


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(iter([b"a"]), id="iterator"),
        pytest.param(io.BytesIO(b"a"), id="file"),
    ],
)
def test_prepare_cache_lookup_streaming_content(content: Iterator[bytes] | io.BytesIO) -> None:
    assert _lookup(content=content) is None


def test_prepare_cache_lookup_files() -> None:
    assert _lookup(files={"file": io.BytesIO(b"a")}) is None


def test_prepare_cache_lookup_does_not_consume_files_iterable() -> None:
    files = iter([("file", io.BytesIO(b"a"))])

    _lookup(files=files)

    assert next(files)[0] == "file"


def test_prepare_cache_lookup_does_not_consume_file() -> None:
    buffer = io.BytesIO(b"abc")

    _lookup(content=buffer)

    assert buffer.read() == b"abc"


def test_prepare_cache_lookup_client_follow_redirects() -> None:
    assert _lookup_key(httpx.Client(follow_redirects=True)) != _lookup_key()


def test_prepare_cache_lookup_call_follow_redirects() -> None:
    assert _lookup_key(follow_redirects=True) == _lookup_key(httpx.Client(follow_redirects=True))


def test_prepare_cache_lookup_call_use_client_default_follow_redirects() -> None:
    assert _lookup_key(follow_redirects=httpx.USE_CLIENT_DEFAULT) == _lookup_key()


def test_prepare_cache_lookup_invalid_argument() -> None:
    with pytest.raises(TypeError, match=r"unexpected keyword argument 'unknown'"):
        _lookup(unknown=1)


################################
#     Tests for _cache_key     #
################################


def _request(method: str = "GET", url: str = "https://example.com", **kwargs: Any) -> httpx.Request:
    return httpx.Request(method, url, **kwargs)


def test_cache_key_value() -> None:
    request = httpx.Request("POST", "https://example.com", content=b"body")
    assert _cache_key(request, follow_redirects=True) == hash_canonical(
        (
            "persista.http.httpx",
            "POST",
            "https://example.com",
            [(b"host", b"example.com"), (b"content-length", b"4")],
            b"body",
            True,
        )
    )


def test_cache_key_same_request() -> None:
    assert _cache_key(_request(), follow_redirects=False) == _cache_key(
        _request(), follow_redirects=False
    )


def test_cache_key_header_names_case_insensitive() -> None:
    assert _cache_key(_request(headers={"X-User": "a"}), follow_redirects=False) == _cache_key(
        _request(headers={"x-user": "a"}), follow_redirects=False
    )


@pytest.mark.parametrize(
    "other",
    [
        pytest.param({"method": "HEAD"}, id="method"),
        pytest.param({"url": "https://example.com/foo"}, id="path"),
        pytest.param({"url": "http://example.com"}, id="scheme"),
        pytest.param({"url": "https://example.com?a=1"}, id="query"),
        pytest.param({"headers": {"x-user": "a"}}, id="new-header"),
        pytest.param({"headers": [("accept", "a"), ("accept", "b")]}, id="repeated-header"),
        pytest.param({"content": b"a"}, id="body"),
        pytest.param({"content": b"\xff"}, id="binary-body"),
    ],
)
def test_cache_key_different_request(other: dict[str, Any]) -> None:
    assert _cache_key(_request(), follow_redirects=False) != _cache_key(
        _request(**other), follow_redirects=False
    )


def test_cache_key_different_header_values() -> None:
    assert _cache_key(_request(headers={"x": b"\xe9"}), follow_redirects=False) != _cache_key(
        _request(headers={"x": b"\xe8"}), follow_redirects=False
    )


def test_cache_key_different_follow_redirects() -> None:
    assert _cache_key(_request(), follow_redirects=False) != _cache_key(
        _request(), follow_redirects=True
    )


def test_cache_key_streaming_body() -> None:
    with pytest.raises(httpx.RequestNotRead, match=r"without having called"):
        _cache_key(_request(content=iter([b"a"])), follow_redirects=False)


########################################
#     Tests for _response_to_entry     #
########################################


def test_response_to_entry() -> None:
    response = httpx.Response(200, headers={"x-user": "a"}, content=b"abc")

    assert _response_to_entry(response) == {
        "status_code": 200,
        "headers": {"x-user": "a"},
        "content": "YWJj",
    }


def test_response_to_entry_empty_content() -> None:
    assert _response_to_entry(httpx.Response(204)) == {
        "status_code": 204,
        "headers": {},
        "content": "",
    }


@pytest.mark.parametrize("header", ["Content-Encoding", "Content-Length", "Transfer-Encoding"])
def test_response_to_entry_drops_transfer_header(header: str) -> None:
    response = httpx.Response(200, headers={header: "identity"})

    assert _response_to_entry(response)["headers"] == {}


def test_response_to_entry_stores_decoded_content() -> None:
    response = httpx.Response(
        200, headers={"content-encoding": "gzip"}, content=gzip.compress(b"abc")
    )

    assert _response_to_entry(response)["content"] == "YWJj"


def test_response_to_entry_does_not_mutate_response() -> None:
    response = httpx.Response(200, content=b"abc")

    _response_to_entry(response)

    assert response.headers["content-length"] == "3"


########################################
#     Tests for _entry_to_response     #
########################################


def test_entry_to_response() -> None:
    request = httpx.Request("GET", "https://example.com")
    entry = {"status_code": 201, "headers": {"x-user": "a"}, "content": "YWJj"}

    response = _entry_to_response(entry, request)

    assert (response.status_code, dict(response.headers), response.content) == (
        201,
        {"x-user": "a", "content-length": "3"},
        b"abc",
    )


def test_entry_to_response_attaches_request() -> None:
    request = httpx.Request("GET", "https://example.com")
    entry = {"status_code": 200, "headers": {}, "content": ""}

    assert _entry_to_response(entry, request).request is request


def test_entry_to_response_does_not_mutate_entry() -> None:
    request = httpx.Request("GET", "https://example.com")
    entry = {"status_code": 200, "headers": {}, "content": "YWJj"}

    _entry_to_response(entry, request)

    assert entry == {"status_code": 200, "headers": {}, "content": "YWJj"}


########################################
#     Helpers of the retry tests       #
########################################


class Script:
    """A transport handler that plays outcomes, one per request.

    An outcome is a status code, a ``(status code, headers)`` tuple, or
    an exception to raise. The last one is repeated. The requests, their
    bodies and the responses are recorded.
    """

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = outcomes
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        self.responses: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        outcome = self.outcomes[min(len(self.requests), len(self.outcomes) - 1)]
        self.requests.append(request)
        self.bodies.append(request.content)
        if isinstance(outcome, Exception):
            raise outcome
        status, headers = outcome if isinstance(outcome, tuple) else (outcome, {})
        response = httpx.Response(status, headers=headers, stream=httpx.ByteStream(b"body"))
        self.responses.append(response)
        return response


def _body_script(*statuses: int) -> tuple[Script, list[bytes]]:
    """Return a script that reads the body of each request, even
    streamed."""
    script = Script(*statuses)
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        return script(request)

    return handler, bodies


class AsyncBodyTransport(httpx.AsyncBaseTransport):
    """An async transport that reads the body of each request before it
    calls a script."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(await request.aread())
        return self.script(request)


IDEMPOTENT = sorted(IDEMPOTENT_METHODS)

TRANSIENT_ERRORS = [
    "ConnectError",
    "ConnectTimeout",
    "ReadError",
    "ReadTimeout",
    "WriteError",
    "WriteTimeout",
    "PoolTimeout",
    "RemoteProtocolError",
    "ProxyError",
]

PERMANENT_ERRORS = ["UnsupportedProtocol", "LocalProtocolError"]


####################################
#     Lifecycle of the clients     #
####################################


def test_http_client_creates_client() -> None:
    with HttpClient() as client:
        assert isinstance(client._client, httpx.Client)


def test_http_client_closes_own_client() -> None:
    with HttpClient() as client:
        pass

    assert client._client.is_closed


def test_http_client_close_own_client_twice() -> None:
    client = HttpClient()
    client.close()
    client.close()

    assert client._client.is_closed


def test_http_client_closes_own_client_on_error() -> None:
    client = HttpClient()
    fail = Mock(side_effect=KeyError("failure"))

    with pytest.raises(KeyError, match=r"failure"), client:
        fail()
    assert client._client.is_closed


def test_http_client_does_not_close_given_client() -> None:
    with _client(Script(200)) as httpx_client:
        with HttpClient(httpx_client):
            pass

        assert not httpx_client.is_closed


def test_http_client_close_does_not_close_given_client() -> None:
    with _client(Script(200)) as httpx_client:
        HttpClient(httpx_client).close()

        assert not httpx_client.is_closed


def test_http_client_enter_returns_wrapper() -> None:
    client = HttpClient()

    with client as entered:
        assert entered is client


def test_http_client_request_after_close() -> None:
    client = HttpClient()
    client.close()

    with pytest.raises(RuntimeError, match=r"the client has been closed"):
        client.get("https://example.com")


def test_http_client_closed_client_does_not_read_cache() -> None:
    httpx_client = _client(Script(200))
    client = HttpClient(httpx_client, cache=_cache())
    client.get("https://example.com")
    httpx_client.close()

    with pytest.raises(RuntimeError, match=r"the client has been closed"):
        client.get("https://example.com")


async def test_async_http_client_creates_client() -> None:
    async with AsyncHttpClient() as client:
        assert isinstance(client._client, httpx.AsyncClient)


async def test_async_http_client_closes_own_client() -> None:
    async with AsyncHttpClient() as client:
        pass

    assert client._client.is_closed


async def test_async_http_client_aclose_own_client_twice() -> None:
    client = AsyncHttpClient()
    await client.aclose()
    await client.aclose()

    assert client._client.is_closed


async def test_async_http_client_does_not_close_given_client() -> None:
    async with _async_client(Script(200)) as httpx_client:
        async with AsyncHttpClient(httpx_client):
            pass

        assert not httpx_client.is_closed


async def test_async_http_client_enter_returns_wrapper() -> None:
    client = AsyncHttpClient()

    async with client as entered:
        assert entered is client


async def test_async_http_client_request_after_close() -> None:
    client = AsyncHttpClient()
    await client.aclose()

    with pytest.raises(RuntimeError, match=r"the client has been closed"):
        await client.get("https://example.com")


async def test_async_http_client_closed_client_does_not_read_cache() -> None:
    httpx_client = _async_client(Script(200))
    client = AsyncHttpClient(httpx_client, cache=_cache())
    await client.get("https://example.com")
    await httpx_client.aclose()

    with pytest.raises(RuntimeError, match=r"the client has been closed"):
        await client.get("https://example.com")


#########################################
#     Arguments of the constructors     #
#########################################


@pytest.mark.parametrize("cls", [HttpClient, AsyncHttpClient])
@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        pytest.param(
            {"max_retries": -1}, ValueError, r"max_retries must be a non-negative", id="retries"
        ),
        pytest.param(
            {"retry_status_codes": ["500"]}, TypeError, r"retry_status_codes", id="status"
        ),
        pytest.param({"retry_methods": "POST"}, TypeError, r"retry_methods", id="methods"),
        pytest.param(
            {"max_delay": float("nan")}, ValueError, r"max_delay must be a finite", id="delay"
        ),
        pytest.param({"cacheable_methods": "GET"}, TypeError, r"cacheable_methods", id="cacheable"),
        pytest.param({"timeout": 1}, TypeError, r"unexpected keyword argument", id="timeout"),
    ],
)
def test_client_invalid_argument(
    cls: type, kwargs: dict[str, Any], error: type[Exception], match: str
) -> None:
    with pytest.raises(error, match=match):
        cls(**kwargs)


@pytest.mark.parametrize(
    ("cls", "name"), [(HttpClient, "Client"), (AsyncHttpClient, "AsyncClient")]
)
def test_client_invalid_argument_creates_no_client(
    monkeypatch: pytest.MonkeyPatch, cls: type, name: str
) -> None:
    factory = Mock()
    monkeypatch.setattr(httpx, name, factory)

    with pytest.raises(ValueError, match=r"max_delay must be a finite"):
        cls(max_delay=-1)
    factory.assert_not_called()


@pytest.mark.parametrize("cls", [HttpClient, AsyncHttpClient])
def test_client_raises_when_httpx_not_available(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    monkeypatch.setattr(
        f"{MODULE}.check_httpx",
        Mock(side_effect=RuntimeError("'httpx' package is required but not installed.")),
    )

    with pytest.raises(RuntimeError, match=r"'httpx' package is required"):
        cls()


###################################
#     Tests for HttpClient        #
#     retries                     #
###################################


@pytest.mark.parametrize("method", IDEMPOTENT)
def test_http_client_retries_idempotent_method(method: str) -> None:
    script = Script(503, 200)

    response = HttpClient(_client(script)).request(method, "https://example.com")

    assert (response.status_code, len(script.requests)) == (200, 2)


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_http_client_does_not_retry_not_idempotent_method(method: str) -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"503 Service Unavailable"):
        client.request(method, "https://example.com")
    assert len(script.requests) == 1


def test_http_client_does_not_retry_post_on_transport_error() -> None:
    script = Script(httpx.ConnectError("refused"), 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.ConnectError, match=r"refused"):
        client.post("https://example.com")
    assert len(script.requests) == 1


def test_http_client_retries_added_method() -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script), retry_methods=IDEMPOTENT_METHODS | {"post"})

    client.post("https://example.com", json={"a": 1})

    assert script.bodies == [b'{"a":1}', b'{"a":1}']


def test_http_client_replaced_retry_methods() -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script), retry_methods={"POST"})

    with pytest.raises(httpx.HTTPStatusError, match=r"503"):
        client.get("https://example.com")
    assert len(script.requests) == 1


def test_http_client_lower_case_method() -> None:
    script = Script(503, 200)

    HttpClient(_client(script)).request("get", "https://example.com")

    assert [request.method for request in script.requests] == ["GET", "GET"]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_http_client_retries_default_status(status: int) -> None:
    script = Script(status, 200)

    HttpClient(_client(script)).get("https://example.com")

    assert len(script.requests) == 2


@pytest.mark.parametrize("status", [400, 404, 413, 501])
def test_http_client_does_not_retry_other_status(status: int) -> None:
    script = Script((status, {"retry-after": "1"}), 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=rf"{status}"):
        client.get("https://example.com")
    assert len(script.requests) == 1


def test_http_client_custom_retry_status_codes() -> None:
    script = Script(418, 200)

    HttpClient(_client(script), retry_status_codes=[418]).get("https://example.com")

    assert len(script.requests) == 2


def test_http_client_call_retry_status_codes() -> None:
    script = Script(418, 200)

    HttpClient(_client(script)).get("https://example.com", retry_status_codes=[418])

    assert len(script.requests) == 2


def test_http_client_exhausts_retries() -> None:
    script = Script(500, 502, 503)
    client = HttpClient(_client(script), max_retries=2)

    with pytest.raises(httpx.HTTPStatusError, match=r"503 Service Unavailable"):
        client.get("https://example.com")
    assert len(script.requests) == 3


def test_http_client_error_has_last_response() -> None:
    script = Script(503)

    with pytest.raises(httpx.HTTPStatusError, match=r"503") as info:
        HttpClient(_client(script)).get("https://example.com")
    assert info.value.response is script.responses[-1]


def test_http_client_returns_successful_status_of_retry_set() -> None:
    script = Script(202)

    response = HttpClient(_client(script), retry_status_codes=[202], max_retries=1).get(
        "https://example.com"
    )

    assert (response.status_code, len(script.requests)) == (202, 2)


def test_http_client_returns_redirect() -> None:
    script = Script((302, {"location": "https://example.com/other"}))

    response = HttpClient(_client(script)).get("https://example.com")

    assert response.status_code == 302


@pytest.mark.parametrize(("kwargs", "count"), [({"max_retries": 0}, 1), ({}, 4)])
def test_http_client_max_retries(kwargs: dict[str, Any], count: int) -> None:
    script = Script(500)
    client = HttpClient(_client(script), **kwargs)

    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.get("https://example.com")
    assert len(script.requests) == count


def test_http_client_call_max_retries() -> None:
    script = Script(500)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.get("https://example.com", max_retries=1)
    assert len(script.requests) == 2


def test_http_client_call_max_retries_does_not_retry_post() -> None:
    script = Script(500)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.post("https://example.com", max_retries=5)
    assert len(script.requests) == 1


def test_http_client_call_override_is_not_kept() -> None:
    script = Script(500)
    client = HttpClient(_client(script), max_retries=1)
    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.get("https://example.com", max_retries=0)

    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.get("https://example.com")
    assert len(script.requests) == 3


def test_http_client_call_invalid_max_retries_sends_nothing() -> None:
    script = Script(200)
    client = HttpClient(_client(script))

    with pytest.raises(ValueError, match=r"max_retries must be a non-negative"):
        client.get("https://example.com", max_retries=-1)
    assert script.requests == []


@pytest.mark.parametrize("name", TRANSIENT_ERRORS)
def test_http_client_retries_transient_error(name: str) -> None:
    script = Script(getattr(httpx, name)("failure"), 200)

    response = HttpClient(_client(script)).get("https://example.com")

    assert (response.status_code, len(script.requests)) == (200, 2)


@pytest.mark.parametrize("name", PERMANENT_ERRORS)
def test_http_client_does_not_retry_permanent_error(name: str) -> None:
    script = Script(getattr(httpx, name)("failure"), 200)
    client = HttpClient(_client(script))

    with pytest.raises(getattr(httpx, name), match=r"failure"):
        client.get("https://example.com")
    assert len(script.requests) == 1


def test_http_client_does_not_retry_other_error() -> None:
    script = Script(httpx.DecodingError("bad content"), 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.DecodingError, match=r"bad content"):
        client.get("https://example.com")
    assert len(script.requests) == 1


def test_http_client_raises_last_transport_error() -> None:
    script = Script(httpx.ConnectError("first"), httpx.ReadTimeout("last"))
    client = HttpClient(_client(script), max_retries=1)

    with pytest.raises(httpx.ReadTimeout, match=r"last"):
        client.get("https://example.com")
    assert len(script.requests) == 2


def test_http_client_raises_transport_error_after_error_response() -> None:
    script = Script(503, httpx.ConnectError("refused"))
    client = HttpClient(_client(script), max_retries=1)

    with pytest.raises(httpx.ConnectError, match=r"refused"):
        client.get("https://example.com")


def test_http_client_exponential_backoff(sleep: Mock) -> None:
    script = Script(503, httpx.ConnectError("refused"), 503, 200)

    HttpClient(_client(script)).get("https://example.com")

    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    ("retry_after", "delay"),
    [
        pytest.param("7", 7.0, id="seconds"),
        pytest.param("-1", 0.0, id="negative"),
        pytest.param("nan", 1.0, id="nan"),
        pytest.param("soon", 1.0, id="garbage"),
        pytest.param("100000", 60.0, id="above-maximum"),
        pytest.param("9" * 5000, 60.0, id="huge"),
        pytest.param("Fri, 31 Dec 9999 23:59:59 GMT", 60.0, id="future-date"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", 0.0, id="past-date"),
    ],
)
def test_http_client_retry_after(sleep: Mock, retry_after: str, delay: float) -> None:
    script = Script((503, {"Retry-After": retry_after}), 200)

    HttpClient(_client(script)).get("https://example.com")

    sleep.assert_called_once_with(delay)


def test_http_client_retry_after_date(sleep: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    # 12 seconds before the date of the header.
    monkeypatch.setattr("persista.http.retry.time.time", lambda: 784111765.0)
    script = Script((429, {"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}), 200)

    HttpClient(_client(script)).get("https://example.com")

    sleep.assert_called_once_with(12.0)


def test_http_client_custom_max_delay(sleep: Mock) -> None:
    script = Script((503, {"Retry-After": "30"}), 200)

    HttpClient(_client(script), max_delay=5).get("https://example.com")

    sleep.assert_called_once_with(5.0)


def test_http_client_success_does_not_sleep(sleep: Mock) -> None:
    HttpClient(_client(Script(200))).get("https://example.com")

    sleep.assert_not_called()


def test_http_client_exhausted_retries_do_not_sleep_after_last_attempt(sleep: Mock) -> None:
    client = HttpClient(_client(Script(500)), max_retries=2)

    with pytest.raises(httpx.HTTPStatusError, match=r"500"):
        client.get("https://example.com")
    assert sleep.call_count == 2


def test_http_client_closes_responses_of_retried_attempts() -> None:
    script = Script(503, 503, 200)

    HttpClient(_client(script)).get("https://example.com")

    assert [response.is_closed for response in script.responses] == [True, True, True]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"content": b"abc"}, id="bytes"),
        pytest.param({"content": "abc"}, id="str"),
        pytest.param({"json": {"a": 1}}, id="json"),
        pytest.param({"data": {"a": "1"}}, id="form"),
    ],
)
def test_http_client_resends_body(kwargs: dict[str, Any]) -> None:
    script = Script(503, 200)

    HttpClient(_client(script)).put("https://example.com", **kwargs)

    assert len(script.bodies) == 2
    assert script.bodies[0] == script.bodies[1] != b""


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(lambda: {"content": iter([b"abc"])}, id="iterator"),
        pytest.param(lambda: {"content": io.BytesIO(b"abc")}, id="file"),
        pytest.param(lambda: {"files": {"f": io.BytesIO(b"abc")}}, id="files"),
        pytest.param(lambda: {"files": iter([("f", b"abc")])}, id="files-iterator"),
    ],
)
def test_http_client_does_not_retry_streaming_body(
    factory: Callable[[], dict[str, Any]],
) -> None:
    handler, bodies = _body_script(503, 200)
    client = HttpClient(_client(handler))

    with pytest.raises(httpx.HTTPStatusError, match=r"503"):
        client.put("https://example.com", **factory())
    assert len(bodies) == 1
    assert b"abc" in bodies[0]


def test_http_client_does_not_retry_streaming_data() -> None:
    handler, bodies = _body_script(503, 200)
    client = HttpClient(_client(handler))

    with (
        pytest.warns(DeprecationWarning, match=r"Use 'content=<...>'"),
        pytest.raises(httpx.HTTPStatusError, match=r"503"),
    ):
        client.put("https://example.com", data=iter([b"abc"]))
    assert bodies == [b"abc"]


def test_http_client_does_not_retry_streaming_body_on_transport_error() -> None:
    script = Script(httpx.ReadError("reset"), 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.ReadError, match=r"reset"):
        client.put("https://example.com", content=iter([b"abc"]))
    assert len(script.requests) == 1


def test_http_client_resends_one_shot_headers() -> None:
    script = Script(503, 200)

    HttpClient(_client(script)).get(
        "https://example.com", headers=zip(["x-user"], ["alice"], strict=True)
    )

    assert [request.headers.get("x-user") for request in script.requests] == ["alice", "alice"]


def test_http_client_none_headers() -> None:
    response = HttpClient(_client(Script(200))).get("https://example.com", headers=None)

    assert response.status_code == 200


def test_http_client_does_not_mutate_headers() -> None:
    headers = {"x-user": "alice"}

    HttpClient(_client(Script(200))).get("https://example.com", headers=headers)

    assert headers == {"x-user": "alice"}


@pytest.mark.parametrize(
    ("timeout", "expected"),
    [
        pytest.param(1, {"connect": 1, "read": 1, "write": 1, "pool": 1}, id="number"),
        pytest.param(
            None, {"connect": None, "read": None, "write": None, "pool": None}, id="disabled"
        ),
    ],
)
def test_http_client_passes_timeout(timeout: float | None, expected: dict[str, Any]) -> None:
    script = Script(503, 200)
    client = HttpClient(httpx.Client(transport=httpx.MockTransport(script), timeout=9))

    client.get("https://example.com", timeout=timeout)

    assert [request.extensions["timeout"] for request in script.requests] == [expected] * 2


def test_http_client_keeps_client_timeout() -> None:
    script = Script(200)
    client = HttpClient(httpx.Client(transport=httpx.MockTransport(script), timeout=9))

    client.get("https://example.com")

    assert script.requests[0].extensions["timeout"] == {
        "connect": 9,
        "read": 9,
        "write": 9,
        "pool": 9,
    }


def test_http_client_sends_client_settings_on_each_attempt() -> None:
    script = Script(503, 200)
    httpx_client = httpx.Client(
        transport=httpx.MockTransport(script),
        base_url="https://example.com",
        headers={"x-user": "alice"},
        auth=("alice", "secret"),
    )

    HttpClient(httpx_client).get("/items")

    assert [
        (str(r.url), r.headers["x-user"], r.headers["authorization"][:5]) for r in script.requests
    ] == [("https://example.com/items", "alice", "Basic")] * 2


@pytest.mark.parametrize("timeout", [1, None])
def test_http_client_cache_ignores_timeout(timeout: float | None) -> None:
    script = Script(200)
    client = HttpClient(_client(script), cache=_cache())
    client.get("https://example.com", timeout=5)

    client.get("https://example.com", timeout=timeout)

    assert len(script.requests) == 1


async def test_async_http_client_cache_ignores_timeout() -> None:
    script = Script(200)
    client = AsyncHttpClient(_async_client(script), cache=_cache())
    await client.get("https://example.com", timeout=5)

    await client.get("https://example.com", timeout=1)

    assert len(script.requests) == 1


def test_http_client_caches_response_of_retry() -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script), cache=_cache())
    client.get("https://example.com")

    client.get("https://example.com")

    assert len(script.requests) == 2


def test_http_client_does_not_log_the_password(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{MODULE}.time.perf_counter", lambda: 0.0)
    script = Script(httpx.ConnectError("https://user:s3cret@example.com"), 503, 200)
    client = HttpClient(_client(script))

    with caplog.at_level(logging.DEBUG, logger="persista"):
        client.get("https://user:s3cret@example.com/items")

    assert [r.getMessage() for r in caplog.records if r.name.startswith("persista")] == [
        "Sending GET https://example.com/items...",
        "Retrying GET https://example.com/items in 1.00s (attempt 1/3, ConnectError)",
        "Response received: HTTP 503 (4 bytes) in 0.00s",
        "Retrying GET https://example.com/items in 2.00s (attempt 2/3, HTTP 503)",
        "Response received: HTTP 200 (4 bytes) in 0.00s",
    ]


########################################
#     Tests for AsyncHttpClient        #
#     retries                          #
########################################


@pytest.mark.parametrize("method", IDEMPOTENT)
async def test_async_http_client_retries_idempotent_method(method: str) -> None:
    script = Script(503, 200)

    response = await AsyncHttpClient(_async_client(script)).request(method, "https://example.com")

    assert (response.status_code, len(script.requests)) == (200, 2)


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_async_http_client_does_not_retry_not_idempotent_method(method: str) -> None:
    script = Script(503, 200)
    client = AsyncHttpClient(_async_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"503 Service Unavailable"):
        await client.request(method, "https://example.com")
    assert len(script.requests) == 1


async def test_async_http_client_retries_added_method() -> None:
    script = Script(503, 200)
    client = AsyncHttpClient(_async_client(script), retry_methods={"POST"})

    await client.post("https://example.com", content=b"abc")

    assert script.bodies == [b"abc", b"abc"]


async def test_async_http_client_call_overrides() -> None:
    script = Script(418)
    client = AsyncHttpClient(_async_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"418"):
        await client.get("https://example.com", max_retries=1, retry_status_codes=[418])
    assert len(script.requests) == 2


async def test_async_http_client_exhausts_retries() -> None:
    script = Script(500, 502, 503)
    client = AsyncHttpClient(_async_client(script), max_retries=2)

    with pytest.raises(httpx.HTTPStatusError, match=r"503 Service Unavailable"):
        await client.get("https://example.com")
    assert len(script.requests) == 3


async def test_async_http_client_returns_redirect() -> None:
    script = Script((302, {"location": "https://example.com/other"}))

    response = await AsyncHttpClient(_async_client(script)).get("https://example.com")

    assert response.status_code == 302


@pytest.mark.parametrize("name", TRANSIENT_ERRORS)
async def test_async_http_client_retries_transient_error(name: str) -> None:
    script = Script(getattr(httpx, name)("failure"), 200)

    response = await AsyncHttpClient(_async_client(script)).get("https://example.com")

    assert (response.status_code, len(script.requests)) == (200, 2)


@pytest.mark.parametrize("name", PERMANENT_ERRORS)
async def test_async_http_client_does_not_retry_permanent_error(name: str) -> None:
    script = Script(getattr(httpx, name)("failure"), 200)
    client = AsyncHttpClient(_async_client(script))

    with pytest.raises(getattr(httpx, name), match=r"failure"):
        await client.get("https://example.com")
    assert len(script.requests) == 1


async def test_async_http_client_raises_last_transport_error() -> None:
    script = Script(httpx.ConnectError("first"), httpx.ReadTimeout("last"))
    client = AsyncHttpClient(_async_client(script), max_retries=1)

    with pytest.raises(httpx.ReadTimeout, match=r"last"):
        await client.get("https://example.com")
    assert len(script.requests) == 2


@pytest.mark.parametrize(("retry_after", "delay"), [("-1", 0.0), ("7", 7.0), ("1e9", 1.0)])
async def test_async_http_client_retry_after(sleep: Mock, retry_after: str, delay: float) -> None:
    script = Script((503, {"Retry-After": retry_after}), 200)

    await AsyncHttpClient(_async_client(script)).get("https://example.com")

    sleep.assert_called_once_with(delay)


async def test_async_http_client_custom_max_delay(sleep: Mock) -> None:
    script = Script((503, {"Retry-After": "30"}), 200)

    await AsyncHttpClient(_async_client(script), max_delay=5).get("https://example.com")

    sleep.assert_called_once_with(5.0)


async def test_async_http_client_closes_responses_of_retried_attempts() -> None:
    script = Script(503, 503, 200)
    await AsyncHttpClient(_async_client(script)).get("https://example.com")

    assert [response.is_closed for response in script.responses] == [True, True, True]


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(lambda: {"content": _async_body()}, id="async-iterator"),
        pytest.param(lambda: {"files": {"f": b"abc"}}, id="files"),
    ],
)
async def test_async_http_client_does_not_retry_streaming_body(
    factory: Callable[[], dict[str, Any]],
) -> None:
    transport = AsyncBodyTransport(Script(503, 200))
    client = AsyncHttpClient(httpx.AsyncClient(transport=transport))

    with pytest.raises(httpx.HTTPStatusError, match=r"503"):
        await client.put("https://example.com", **factory())
    assert len(transport.bodies) == 1
    assert b"abc" in transport.bodies[0]


async def _async_body() -> AsyncIterator[bytes]:
    yield b"abc"


async def test_async_http_client_resends_one_shot_headers() -> None:
    script = Script(503, 200)

    await AsyncHttpClient(_async_client(script)).get(
        "https://example.com", headers=zip(["x-user"], ["alice"], strict=True)
    )

    assert [request.headers.get("x-user") for request in script.requests] == ["alice", "alice"]


async def test_async_http_client_passes_timeout() -> None:
    script = Script(200)
    client = AsyncHttpClient(httpx.AsyncClient(transport=httpx.MockTransport(script), timeout=9))

    await client.get("https://example.com", timeout=1)

    assert script.requests[0].extensions["timeout"] == {
        "connect": 1,
        "read": 1,
        "write": 1,
        "pool": 1,
    }


###########################################
#     Tests for HttpClient._send          #
###########################################


def test_http_client_send_returns_response() -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script))

    response = client._send("GET", "https://example.com", RetryPolicy(), {})

    assert response is script.responses[-1]


def test_http_client_send_uses_policy() -> None:
    script = Script(503, 200)
    client = HttpClient(_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"503"):
        client._send("GET", "https://example.com", RetryPolicy(max_retries=0), {})
    assert len(script.requests) == 1


async def test_async_http_client_send_returns_response() -> None:
    script = Script(503, 200)
    client = AsyncHttpClient(_async_client(script))

    response = await client._send("GET", "https://example.com", RetryPolicy(), {})

    assert response is script.responses[-1]


async def test_async_http_client_send_uses_policy() -> None:
    script = Script(503, 200)
    client = AsyncHttpClient(_async_client(script))

    with pytest.raises(httpx.HTTPStatusError, match=r"503"):
        await client._send("GET", "https://example.com", RetryPolicy(max_retries=0), {})
    assert len(script.requests) == 1


###########################################
#     Tests for _check_client_is_open     #
###########################################


@pytest.mark.parametrize("name", ["Client", "AsyncClient"])
def test_check_client_is_open(name: str) -> None:
    _check_client_is_open(getattr(httpx, name)())


def test_check_client_is_open_closed() -> None:
    client = httpx.Client()
    client.close()

    with pytest.raises(RuntimeError, match=r"the client has been closed"):
        _check_client_is_open(client)


#########################################
#     Tests for _is_replayable_body     #
#########################################


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="no-body"),
        pytest.param({"content": None, "data": None, "files": None}, id="none"),
        pytest.param({"content": b""}, id="empty-bytes"),
        pytest.param({"content": b"a"}, id="bytes"),
        pytest.param({"content": "a"}, id="str"),
        pytest.param({"data": b"a"}, id="bytes-data"),
        pytest.param({"data": {"a": "1"}}, id="form"),
        pytest.param({"json": [1, 2]}, id="json"),
        pytest.param({"files": {}}, id="empty-files"),
    ],
)
def test_is_replayable_body_true(kwargs: dict[str, Any]) -> None:
    assert _is_replayable_body(kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"content": iter([b"a"])}, id="iterator"),
        pytest.param({"content": [b"a"]}, id="list"),
        pytest.param({"content": io.BytesIO(b"a")}, id="file"),
        pytest.param({"data": iter([b"a"])}, id="iterator-data"),
        pytest.param({"files": {"f": b"a"}}, id="files"),
        pytest.param({"data": {"a": "1"}, "files": [("f", b"a")]}, id="form-and-files"),
        pytest.param({"content": b"a", "data": iter([b"a"])}, id="one-of-two"),
    ],
)
def test_is_replayable_body_false(kwargs: dict[str, Any]) -> None:
    assert not _is_replayable_body(kwargs)


def test_is_replayable_body_does_not_consume() -> None:
    content = iter([b"a"])

    _is_replayable_body({"content": content})

    assert next(content) == b"a"


#########################################
#     Tests for _is_transient_error     #
#########################################


@pytest.mark.parametrize("name", TRANSIENT_ERRORS)
def test_is_transient_error_true(name: str) -> None:
    assert _is_transient_error(getattr(httpx, name)("failure"))


@pytest.mark.parametrize("name", PERMANENT_ERRORS)
def test_is_transient_error_false(name: str) -> None:
    assert not _is_transient_error(getattr(httpx, name)("failure"))


#################################
#     Tests for _plan_retry     #
#################################


def _plan(outcome: Any, attempt: int = 1, max_retries: int = 3) -> float | None:
    return _plan_retry(
        outcome,
        policy=RetryPolicy(),
        attempt=attempt,
        max_retries=max_retries,
        method="GET",
        url="https://example.com",
    )


@pytest.mark.parametrize(("attempt", "delay"), [(1, 1.0), (3, 4.0), (4, None)])
def test_plan_retry_status(attempt: int, delay: float | None) -> None:
    assert _plan(httpx.Response(503), attempt=attempt) == delay


def test_plan_retry_retry_after() -> None:
    assert _plan(httpx.Response(503, headers={"retry-after": "9"})) == 9.0


def test_plan_retry_other_status() -> None:
    assert _plan(httpx.Response(404)) is None


@pytest.mark.parametrize(("attempt", "delay"), [(1, 1.0), (4, None)])
def test_plan_retry_transient_error(attempt: int, delay: float | None) -> None:
    assert _plan(httpx.ConnectError("failure"), attempt=attempt) == delay


def test_plan_retry_permanent_error() -> None:
    assert _plan(httpx.UnsupportedProtocol("failure")) is None


def test_plan_retry_no_retry_allowed() -> None:
    assert _plan(httpx.Response(503), max_retries=0) is None


def test_plan_retry_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="persista"):
        _plan(httpx.Response(503))

    assert caplog.messages == ["Retrying GET https://example.com in 1.00s (attempt 1/3, HTTP 503)"]
