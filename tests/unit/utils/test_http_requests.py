from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from persista.utils.http_requests import create_session, fetch_response

requests = pytest.importorskip("requests")


MODULE = "persista.utils.http_requests"


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
    assert retry.status_forcelist == [429, 500, 502, 503, 504]


def test_create_session_custom_max_retries() -> None:
    session = create_session(max_retries=5)

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.total == 5


def test_create_session_custom_retry_status_codes() -> None:
    session = create_session(retry_status_codes=[418, 500])

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.status_forcelist == [418, 500]


def test_create_session_custom_backoff_factor() -> None:
    session = create_session(backoff_factor=2.5)

    retry = session.get_adapter("https://example.com").max_retries

    assert retry.backoff_factor == 2.5


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
        max_retries=3, retry_status_codes=None, backoff_factor=1
    )
    session.close.assert_called_once()


def test_fetch_response_own_session_is_closed_on_error() -> None:
    session = Mock(get=Mock(side_effect=requests.exceptions.ConnectionError("boom")))

    with (
        patch(f"{MODULE}.create_session", return_value=session),
        pytest.raises(requests.exceptions.ConnectionError),
    ):
        fetch_response("https://example.com")

    session.close.assert_called_once()


def test_fetch_response_forwards_max_retries_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", max_retries=7)

    mock_create_session.assert_called_once_with(
        max_retries=7, retry_status_codes=None, backoff_factor=1
    )


def test_fetch_response_forwards_retry_status_codes_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", retry_status_codes=[418, 500])

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=[418, 500], backoff_factor=1
    )


def test_fetch_response_forwards_backoff_factor_to_create_session() -> None:
    response = Mock(status_code=200, content=b"")
    session = Mock(get=Mock(return_value=response))

    with patch(f"{MODULE}.create_session", return_value=session) as mock_create_session:
        fetch_response("https://example.com", backoff_factor=0.5)

    mock_create_session.assert_called_once_with(
        max_retries=3, retry_status_codes=None, backoff_factor=0.5
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
            session=session,
        )

    mock_create_session.assert_not_called()


def test_fetch_response_raises_http_error_on_4xx() -> None:
    response = Mock(status_code=404, content=b"")
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    session = Mock(get=Mock(return_value=response))

    with pytest.raises(requests.exceptions.HTTPError):
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
