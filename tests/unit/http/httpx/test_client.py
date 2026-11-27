from __future__ import annotations

import gzip
import io
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from persista.cache import Cache
from persista.http.httpx.client import (
    AsyncHttpClient,
    HttpClient,
    _cache_key,
    _entry_to_response,
    _prepare_cache_lookup,
    _response_to_entry,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

httpx = pytest.importorskip("httpx")


MODULE = "persista.http.httpx.method"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.time.sleep", Mock())

    async def fake_async_sleep(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(f"{MODULE}.asyncio.sleep", fake_async_sleep)


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

    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.com")
    with pytest.raises(httpx.HTTPStatusError):
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
