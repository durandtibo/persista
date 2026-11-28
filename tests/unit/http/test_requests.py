from __future__ import annotations

import importlib.util
import logging
from typing import Any
from unittest.mock import Mock, patch

import pytest

from persista.http.requests import _BoundedRetry, create_session, fetch_response
from persista.utils.imports import is_urllib3_available

requests = pytest.importorskip("requests")

if is_urllib3_available():
    from urllib3.exceptions import (
        MaxRetryError,
        NewConnectionError,
        ReadTimeoutError,
        SSLError,
    )
    from urllib3.response import HTTPResponse


MODULE = "persista.http.requests"


############################
#     create_session       #
############################


def test_create_session_returns_session() -> None:
    session = create_session()

    assert isinstance(session, requests.Session)


def test_create_session_mounts_adapter_on_both_schemes() -> None:
    session = create_session()

    assert session.get_adapter("https://example.com") is session.get_adapter("http://example.com")


def test_create_session_default_retry_configuration() -> None:
    session = create_session()

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.total == 3
    assert retry.backoff_factor == 1
    assert retry.status_forcelist == frozenset({429, 500, 502, 503, 504})


def test_create_session_custom_max_retries() -> None:
    session = create_session(max_retries=5)

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.total == 5


def test_create_session_custom_retry_status_codes() -> None:
    session = create_session(retry_status_codes=[418, 500])

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.status_forcelist == frozenset({418, 500})


def test_create_session_custom_backoff_factor() -> None:
    session = create_session(backoff_factor=2.5)

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.backoff_factor == 2.5


def test_create_session_retries_get_only() -> None:
    retry = create_session().get_adapter("https://example.com").max_retries

    assert retry.allowed_methods == frozenset({"GET"})


def test_create_session_default_max_delay() -> None:
    retry = create_session().get_adapter("https://example.com").max_retries

    assert retry.backoff_max == 60.0


def test_create_session_custom_max_delay() -> None:
    retry = create_session(max_delay=5).get_adapter("https://example.com").max_retries

    assert retry.backoff_max == 5.0


def test_create_session_uses_bounded_retry() -> None:
    retry = create_session().get_adapter("https://example.com").max_retries

    assert isinstance(retry, _BoundedRetry)


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        pytest.param(
            {"max_retries": -1}, ValueError, r"max_retries must be a non-negative", id="retries"
        ),
        pytest.param(
            {"max_retries": None}, TypeError, r"max_retries must be an int", id="retries-none"
        ),
        pytest.param(
            {"retry_status_codes": [1000]}, ValueError, r"between 100 and 599", id="status"
        ),
        pytest.param(
            {"max_delay": float("inf")}, ValueError, r"max_delay must be a finite", id="delay"
        ),
        pytest.param(
            {"backoff_factor": -1}, ValueError, r"backoff_factor must be a finite", id="negative"
        ),
        pytest.param(
            {"backoff_factor": float("nan")},
            ValueError,
            r"backoff_factor must be a finite",
            id="nan",
        ),
        pytest.param({"backoff_factor": "1"}, TypeError, r"must be real number", id="backoff-type"),
    ],
)
def test_create_session_invalid_argument(
    kwargs: dict[str, Any], error: type[Exception], match: str
) -> None:
    with pytest.raises(error, match=match):
        create_session(**kwargs)


def test_module_can_be_imported_without_urllib3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("persista.utils.imports.is_urllib3_available", lambda: False)
    spec = importlib.util.find_spec(MODULE)
    # A new module object, so the imported module is not modified.
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module._BoundedRetry.__bases__ == (object,)


def test_create_session_raises_when_requests_not_available() -> None:
    error_message = "'requests' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    with (
        patch(f"{MODULE}.check_requests", _raise),
        pytest.raises(RuntimeError, match=r"'requests' package is required but not installed."),
    ):
        create_session()


############################
#     fetch_response       #
############################


def test_fetch_response_success() -> None:
    response = Mock(status_code=200, content=b"{}")
    session = Mock(get=Mock(return_value=response))

    result = fetch_response("https://example.com", session=session)

    assert result is response
    response.raise_for_status.assert_called_once()


def test_fetch_response_passes_url_headers_and_timeout() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    fetch_response(
        "https://example.com", timeout=10, headers={"X-Custom": "value"}, session=session
    )

    session.get.assert_called_once_with(
        "https://example.com", headers={"X-Custom": "value"}, timeout=10
    )


def test_fetch_response_provided_session_is_not_closed() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    fetch_response("https://example.com", session=session)

    session.close.assert_not_called()


def test_fetch_response_own_session_is_closed() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com")

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=None, backoff_factor=1, max_delay=60.0
    )
    session.close.assert_called_once()


def test_fetch_response_own_session_is_closed_on_error() -> None:
    session = Mock(get=Mock(side_effect=requests.exceptions.ConnectionError("boom")))

    with (
        patch(f"{MODULE}.create_session", return_value=session),
        pytest.raises(requests.exceptions.ConnectionError, match=r"boom"),
    ):
        fetch_response("https://example.com")

    session.close.assert_called_once()


def test_fetch_response_forwards_max_retries_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", max_retries=7)

    mock_create_session.assert_called_once_with(
        max_retries=7, retry_status_codes=None, backoff_factor=1, max_delay=60.0
    )


def test_fetch_response_forwards_retry_status_codes_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", retry_status_codes=[418, 500])

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=[418, 500], backoff_factor=1, max_delay=60.0
    )


def test_fetch_response_forwards_backoff_factor_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", backoff_factor=0.5)

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=None, backoff_factor=0.5, max_delay=60.0
    )


def test_fetch_response_forwards_max_delay_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", max_delay=5)

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=None, backoff_factor=1, max_delay=5
    )


def test_fetch_response_ignores_retry_kwargs_when_session_provided() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session") as mock_create_session:
        fetch_response(
            "https://example.com",
            max_retries=7,
            retry_status_codes=[418],
            backoff_factor=9,
            max_delay=9,
            session=session,
        )

    mock_create_session.assert_not_called()


def test_fetch_response_raises_http_error_on_4xx() -> None:
    response = Mock(status_code=404, content=b"")
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    session = Mock(get=Mock(return_value=response))

    with pytest.raises(requests.exceptions.HTTPError, match=r"404"):
        fetch_response("https://example.com", session=session)


def test_fetch_response_raises_when_requests_not_available() -> None:
    error_message = "'requests' package is required but not installed."

    def _raise() -> None:
        raise RuntimeError(error_message)

    with (
        patch(f"{MODULE}.check_requests", _raise),
        pytest.raises(RuntimeError, match=r"'requests' package is required but not installed."),
    ):
        fetch_response("https://example.com")


def test_fetch_response_does_not_log_the_password(caplog: pytest.LogCaptureFixture) -> None:
    session = Mock()
    session.get.return_value = Mock(status_code=200, content=b"")
    with caplog.at_level(logging.DEBUG, logger="persista"):
        fetch_response("https://user:s3cret@example.com/items", session=session)
    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == "Fetching https://example.com/items..."


###################################
#     Tests for _BoundedRetry     #
###################################


def _retry(**kwargs: Any) -> _BoundedRetry:
    options = {"total": 3, "allowed_methods": frozenset({"GET"}), "backoff_max": 60.0}
    return _BoundedRetry(**(options | kwargs))


def _response(retry_after: str | None = None, status: int = 503) -> HTTPResponse:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return HTTPResponse(status=status, headers=headers)


@pytest.fixture
def sleep(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock()
    monkeypatch.setattr(f"{MODULE}.time.sleep", mock)
    return mock


@pytest.mark.parametrize(
    ("retry_after", "delay"),
    [
        pytest.param("0", 0.0, id="zero"),
        pytest.param("5", 5.0, id="seconds"),
        pytest.param("-1", 0.0, id="negative"),
        pytest.param("100000", 60.0, id="above-maximum"),
        pytest.param("9" * 5000, 60.0, id="huge"),
        pytest.param("Fri, 31 Dec 9999 23:59:59 GMT", 60.0, id="future-date"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", 0.0, id="past-date"),
        pytest.param("nan", None, id="nan"),
        pytest.param("soon", None, id="garbage"),
        pytest.param(None, None, id="no-header"),
    ],
)
def test_bounded_retry_get_retry_after(retry_after: str | None, delay: float | None) -> None:
    assert _retry().get_retry_after(_response(retry_after)) == delay


@pytest.mark.parametrize(("retry_after", "delay"), [("0", 0.0), ("5", 5.0), ("100", 60.0)])
def test_bounded_retry_sleep_for_retry(sleep: Mock, retry_after: str, delay: float) -> None:
    _retry().sleep_for_retry(_response(retry_after))

    sleep.assert_called_once_with(delay)


@pytest.mark.parametrize(("retry_after", "slept"), [("0", True), ("garbage", False), (None, False)])
@pytest.mark.usefixtures("sleep")
def test_bounded_retry_sleep_for_retry_result(retry_after: str | None, slept: bool) -> None:
    assert _retry().sleep_for_retry(_response(retry_after)) is slept


def test_bounded_retry_sleep_zero_does_not_use_backoff(sleep: Mock) -> None:
    retry = _retry(backoff_factor=1).increment("GET", "/", response=_response())
    retry = retry.increment("GET", "/", response=_response())

    retry.sleep(_response("0"))

    sleep.assert_called_once_with(0.0)


def test_bounded_retry_sleep_invalid_header_uses_backoff(sleep: Mock) -> None:
    retry = _retry(backoff_factor=1).increment("GET", "/", response=_response())
    retry = retry.increment("GET", "/", response=_response())

    retry.sleep(_response("garbage"))

    sleep.assert_called_once_with(2.0)


@pytest.mark.parametrize(("attempts", "delay"), [(1, 0), (2, 2.0), (3, 4.0), (8, 60.0)])
def test_bounded_retry_get_backoff_time(attempts: int, delay: float) -> None:
    retry = _retry(total=10, backoff_factor=1)
    for _ in range(attempts):
        retry = retry.increment("GET", "/", response=_response())

    assert retry.get_backoff_time() == delay


@pytest.mark.parametrize(("backoff_factor", "delay"), [(0.5, 60.0), (0.0, 0.0)])
def test_bounded_retry_get_backoff_time_too_many_attempts(
    backoff_factor: float, delay: float
) -> None:
    history = _retry().increment("GET", "/", response=_response()).history
    retry = _retry(backoff_factor=backoff_factor, history=history * 1100)

    assert retry.get_backoff_time() == delay


@pytest.mark.parametrize("status", [413, 429, 503])
def test_bounded_retry_is_retry_ignores_unlisted_status_with_retry_after(status: int) -> None:
    assert not _retry(status_forcelist={500}).is_retry("GET", status, has_retry_after=True)


def test_bounded_retry_is_retry_listed_status() -> None:
    assert _retry(status_forcelist={503}).is_retry("GET", 503)


def test_bounded_retry_is_retry_other_method() -> None:
    assert not _retry(status_forcelist={503}).is_retry("POST", 503, has_retry_after=True)


def test_bounded_retry_increment_keeps_class() -> None:
    retry = _retry().increment("GET", "/", response=_response())

    assert isinstance(retry, _BoundedRetry)


def test_bounded_retry_increment_keeps_max_delay() -> None:
    retry = _retry(backoff_max=7.0).increment("GET", "/", response=_response())

    assert retry.backoff_max == 7.0


def test_bounded_retry_increment_retried_method() -> None:
    error = NewConnectionError(None, "refused")

    assert _retry().increment("GET", "/", error=error).total == 2


@pytest.mark.parametrize("method", ["POST", "post", "PUT", "DELETE"])
def test_bounded_retry_increment_other_method_connection_error(method: str) -> None:
    with pytest.raises(MaxRetryError, match=r"refused"):
        _retry().increment(method, "/", error=NewConnectionError(None, "refused"))


def test_bounded_retry_increment_other_method_other_error() -> None:
    with pytest.raises(MaxRetryError, match=r"bad certificate"):
        _retry().increment("POST", "/", error=SSLError("bad certificate"))


def test_bounded_retry_increment_other_method_read_error() -> None:
    with pytest.raises(ReadTimeoutError, match=r"too slow"):
        _retry().increment("POST", "/", error=ReadTimeoutError(None, "/", "too slow"))


def test_bounded_retry_increment_any_method_allowed() -> None:
    error = NewConnectionError(None, "refused")

    assert _retry(allowed_methods=None).increment("POST", "/", error=error).total == 2


def test_bounded_retry_increment_unknown_method() -> None:
    error = NewConnectionError(None, "refused")

    assert _retry().increment(error=error).total == 2


def test_bounded_retry_increment_does_not_mutate() -> None:
    retry = _retry()

    with pytest.raises(MaxRetryError, match=r"refused"):
        retry.increment("POST", "/", error=NewConnectionError(None, "refused"))
    assert retry.total == 3
