from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import pytest

from persista.http.httpx import (
    _get_retry_delay,
    get_response,
    get_response_async,
    send_request,
    send_request_async,
)

if TYPE_CHECKING:
    from collections.abc import Callable

httpx = pytest.importorskip("httpx")


MODULE = "persista.http.httpx"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock()

    async def fake_async_sleep(*args: Any, **kwargs: Any) -> None:
        mock(*args, **kwargs)

    monkeypatch.setattr(f"{MODULE}.time.sleep", mock)
    monkeypatch.setattr(f"{MODULE}.asyncio.sleep", fake_async_sleep)
    return mock


def _counting_handler(
    statuses: list[int], json: dict[str, object] | None = None
) -> tuple[Callable, Mock]:
    calls = Mock(side_effect=iter(statuses))

    def handler(request: httpx.Request) -> httpx.Response:
        status = calls()
        return httpx.Response(status, json=json, request=request)

    return handler, calls


def _client(handler: Callable) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _async_client(handler: Callable) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


############################
#      get_response       #
############################


def test_get_response_success_first_try() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})

    response = get_response("https://example.com", client=_client(handler))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 1


def test_get_response_passes_headers() -> None:
    received: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(request.headers)
        return httpx.Response(200)

    get_response("https://example.com", client=_client(handler), headers={"X-Custom": "value"})

    assert received["x-custom"] == "value"


def test_get_response_forwards_kwargs_to_client_get() -> None:
    received_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_params.update(request.url.params)
        return httpx.Response(200)

    get_response("https://example.com", client=_client(handler), params={"q": "value"})

    assert received_params == {"q": "value"}


def test_get_response_provided_client_is_not_closed() -> None:
    handler, _ = _counting_handler([200])
    client = _client(handler)

    get_response("https://example.com", client=client)

    assert not client.is_closed


def test_get_response_own_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _ = _counting_handler([200])
    client = _client(handler)
    monkeypatch.setattr(f"{MODULE}.httpx.Client", lambda **_kwargs: client)

    get_response("https://example.com")

    assert client.is_closed


def test_get_response_retries_default_status_codes_then_succeeds(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})

    response = get_response("https://example.com", client=_client(handler), max_retries=3)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


def test_get_response_exhausts_retries_raises_http_status_error() -> None:
    handler, calls = _counting_handler([500, 500, 500])

    with pytest.raises(httpx.HTTPStatusError):
        get_response("https://example.com", client=_client(handler), max_retries=2)

    assert calls.call_count == 3


def test_get_response_max_retries_zero_does_not_retry(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([500])

    with pytest.raises(httpx.HTTPStatusError):
        get_response("https://example.com", client=_client(handler), max_retries=0)

    assert calls.call_count == 1
    no_sleep.assert_not_called()


def test_get_response_status_not_in_retry_set_raises_immediately(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([404])

    with pytest.raises(httpx.HTTPStatusError):
        get_response("https://example.com", client=_client(handler), max_retries=3)

    assert calls.call_count == 1
    no_sleep.assert_not_called()


def test_get_response_custom_retry_status_codes() -> None:
    handler, calls = _counting_handler([418, 200], json={"ok": True})

    response = get_response(
        "https://example.com",
        client=_client(handler),
        max_retries=1,
        retry_status_codes={418},
    )

    assert response.status_code == 200
    assert calls.call_count == 2


def test_get_response_retries_on_transport_error_then_succeeds(no_sleep: Mock) -> None:
    attempts = Mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200)])

    def handler(_request: httpx.Request) -> httpx.Response:
        result = attempts()
        if isinstance(result, Exception):
            raise result
        return result

    response = get_response("https://example.com", client=_client(handler), max_retries=1)

    assert response.status_code == 200
    assert attempts.call_count == 2
    assert no_sleep.call_count == 1


def test_get_response_transport_error_exhausted_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = "boom"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(httpx.ConnectError):
        get_response("https://example.com", client=_client(handler), max_retries=2)


def test_get_response_honors_retry_after_header(no_sleep: Mock) -> None:
    calls = Mock(side_effect=[503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = calls()
        headers = {"Retry-After": "5"} if status == 503 else {}
        return httpx.Response(status, headers=headers, request=request)

    get_response("https://example.com", client=_client(handler), max_retries=1)

    no_sleep.assert_called_once_with(5.0)


def test_get_response_exponential_backoff_without_retry_after(no_sleep: Mock) -> None:
    handler, _ = _counting_handler([503, 503, 503, 200])

    get_response("https://example.com", client=_client(handler), max_retries=3)

    assert [call.args[0] for call in no_sleep.call_args_list] == [1.0, 2.0, 4.0]


def test_get_response_raises_when_httpx_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    error_message = "'httpx' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    monkeypatch.setattr(f"{MODULE}.check_httpx", _raise)

    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        get_response("https://example.com")


############################
#      send_request        #
############################


def test_send_request_get_success_first_try() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})

    response = send_request("GET", "https://example.com", client=_client(handler))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 1


def test_send_request_post_forwards_method_and_json_body() -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["body"] = request.content
        return httpx.Response(201)

    response = send_request(
        "POST", "https://example.com", client=_client(handler), json={"name": "value"}
    )

    assert response.status_code == 201
    assert received["method"] == "POST"
    assert received["body"] == b'{"name":"value"}'


def test_send_request_retries_default_status_codes_then_succeeds(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})

    response = send_request("PUT", "https://example.com", client=_client(handler), max_retries=3)

    assert response.status_code == 200
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


def test_send_request_raises_when_httpx_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    error_message = "'httpx' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    monkeypatch.setattr(f"{MODULE}.check_httpx", _raise)

    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        send_request("GET", "https://example.com")


############################
#    get_response_async   #
############################


async def test_get_response_async_success_first_try() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})

    response = await get_response_async("https://example.com", client=_async_client(handler))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 1


async def test_get_response_async_passes_headers() -> None:
    received: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(request.headers)
        return httpx.Response(200)

    await get_response_async(
        "https://example.com", client=_async_client(handler), headers={"X-Custom": "value"}
    )

    assert received["x-custom"] == "value"


async def test_get_response_async_forwards_kwargs_to_client_get() -> None:
    received_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_params.update(request.url.params)
        return httpx.Response(200)

    await get_response_async(
        "https://example.com", client=_async_client(handler), params={"q": "value"}
    )

    assert received_params == {"q": "value"}


async def test_get_response_async_provided_client_is_not_closed() -> None:
    handler, _ = _counting_handler([200])
    client = _async_client(handler)

    await get_response_async("https://example.com", client=client)

    assert not client.is_closed


async def test_get_response_async_own_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _ = _counting_handler([200])
    client = _async_client(handler)
    monkeypatch.setattr(f"{MODULE}.httpx.AsyncClient", lambda **_kwargs: client)

    await get_response_async("https://example.com")

    assert client.is_closed


async def test_get_response_async_retries_default_status_codes_then_succeeds(
    no_sleep: Mock,
) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})

    response = await get_response_async(
        "https://example.com", client=_async_client(handler), max_retries=3
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


async def test_get_response_async_exhausts_retries_raises_http_status_error() -> None:
    handler, calls = _counting_handler([500, 500, 500])

    with pytest.raises(httpx.HTTPStatusError):
        await get_response_async(
            "https://example.com", client=_async_client(handler), max_retries=2
        )

    assert calls.call_count == 3


async def test_get_response_async_max_retries_zero_does_not_retry(no_sleep: Mock) -> None:
    handler, calls = _counting_handler([500])

    with pytest.raises(httpx.HTTPStatusError):
        await get_response_async(
            "https://example.com", client=_async_client(handler), max_retries=0
        )

    assert calls.call_count == 1
    no_sleep.assert_not_called()


async def test_get_response_async_status_not_in_retry_set_raises_immediately(
    no_sleep: Mock,
) -> None:
    handler, calls = _counting_handler([404])

    with pytest.raises(httpx.HTTPStatusError):
        await get_response_async(
            "https://example.com", client=_async_client(handler), max_retries=3
        )

    assert calls.call_count == 1
    no_sleep.assert_not_called()


async def test_get_response_async_custom_retry_status_codes() -> None:
    handler, calls = _counting_handler([418, 200], json={"ok": True})

    response = await get_response_async(
        "https://example.com",
        client=_async_client(handler),
        max_retries=1,
        retry_status_codes={418},
    )

    assert response.status_code == 200
    assert calls.call_count == 2


async def test_get_response_async_retries_on_transport_error_then_succeeds(
    no_sleep: Mock,
) -> None:
    attempts = Mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200)])

    def handler(_request: httpx.Request) -> httpx.Response:
        result = attempts()
        if isinstance(result, Exception):
            raise result
        return result

    response = await get_response_async(
        "https://example.com", client=_async_client(handler), max_retries=1
    )

    assert response.status_code == 200
    assert attempts.call_count == 2
    assert no_sleep.call_count == 1


async def test_get_response_async_transport_error_exhausted_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = "boom"
        raise httpx.ConnectError(message, request=request)

    with pytest.raises(httpx.ConnectError):
        await get_response_async(
            "https://example.com", client=_async_client(handler), max_retries=2
        )


async def test_get_response_async_honors_retry_after_header(no_sleep: Mock) -> None:
    calls = Mock(side_effect=[503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = calls()
        headers = {"Retry-After": "5"} if status == 503 else {}
        return httpx.Response(status, headers=headers, request=request)

    await get_response_async("https://example.com", client=_async_client(handler), max_retries=1)

    no_sleep.assert_called_once_with(5.0)


async def test_get_response_async_exponential_backoff_without_retry_after(
    no_sleep: Mock,
) -> None:
    handler, _ = _counting_handler([503, 503, 503, 200])

    await get_response_async("https://example.com", client=_async_client(handler), max_retries=3)

    assert [call.args[0] for call in no_sleep.call_args_list] == [1.0, 2.0, 4.0]


async def test_get_response_async_raises_when_httpx_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = "'httpx' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    monkeypatch.setattr(f"{MODULE}.check_httpx", _raise)

    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await get_response_async("https://example.com")


############################
#     send_request_async   #
############################


async def test_send_request_async_get_success_first_try() -> None:
    handler, calls = _counting_handler([200], json={"ok": True})

    response = await send_request_async("GET", "https://example.com", client=_async_client(handler))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls.call_count == 1


async def test_send_request_async_post_forwards_method_and_json_body() -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["method"] = request.method
        received["body"] = request.content
        return httpx.Response(201)

    response = await send_request_async(
        "POST", "https://example.com", client=_async_client(handler), json={"name": "value"}
    )

    assert response.status_code == 201
    assert received["method"] == "POST"
    assert received["body"] == b'{"name":"value"}'


async def test_send_request_async_retries_default_status_codes_then_succeeds(
    no_sleep: Mock,
) -> None:
    handler, calls = _counting_handler([503, 502, 200], json={"ok": True})

    response = await send_request_async(
        "PUT", "https://example.com", client=_async_client(handler), max_retries=3
    )

    assert response.status_code == 200
    assert calls.call_count == 3
    assert no_sleep.call_count == 2


async def test_send_request_async_raises_when_httpx_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = "'httpx' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    monkeypatch.setattr(f"{MODULE}.check_httpx", _raise)

    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        await send_request_async("GET", "https://example.com")


############################
#     _get_retry_delay     #
############################


def test_get_retry_delay_uses_retry_after_header() -> None:
    response = httpx.Response(503, headers={"Retry-After": "2.5"})

    assert _get_retry_delay(response, attempt=1) == 2.5


def test_get_retry_delay_ignores_invalid_retry_after_header() -> None:
    response = httpx.Response(503, headers={"Retry-After": "not-a-number"})

    assert _get_retry_delay(response, attempt=3) == 4.0


@pytest.mark.parametrize(("attempt", "expected"), [(1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0)])
def test_get_retry_delay_exponential_backoff(attempt: int, expected: float) -> None:
    response = httpx.Response(503)

    assert _get_retry_delay(response, attempt=attempt) == expected
