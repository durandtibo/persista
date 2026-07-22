from __future__ import annotations

import pytest

from persista.testing.fixtures import requests_available, requests_not_available
from persista.utils.imports import is_requests_available

if is_requests_available():
    from persista.http.requests import fetch_response

REMOTE_URL = "https://jsonplaceholder.typicode.com/todos/1"


############################
#     fetch_response       #
############################


@requests_available
def test_fetch_response_success_against_remote_url() -> None:
    response = fetch_response(REMOTE_URL, timeout=10)

    assert response.status_code == 200
    assert response.json()["id"] == 1


@requests_not_available
def test_fetch_response_raises_without_requests() -> None:
    with pytest.raises(RuntimeError, match=r"'requests' package is required but not installed."):
        fetch_response("http://127.0.0.1:1")
