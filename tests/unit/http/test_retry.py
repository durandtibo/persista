from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from persista.http.retry import (
    DEFAULT_MAX_DELAY,
    DEFAULT_RETRY_STATUS_CODES,
    IDEMPOTENT_METHODS,
    RetryPolicy,
    normalize_methods,
    normalize_status_codes,
    parse_retry_after,
    validate_max_delay,
    validate_max_retries,
)

# Sun, 06 Nov 1994 08:49:37 GMT, in seconds since the epoch.
DATE = 784111777.0


#######################################
#     Tests for parse_retry_after     #
#######################################


@pytest.mark.parametrize(
    ("value", "delay"),
    [
        pytest.param("0", 0.0, id="zero"),
        pytest.param("120", 120.0, id="seconds"),
        pytest.param("  7  ", 7.0, id="spaces"),
        pytest.param("007", 7.0, id="leading-zeros"),
        pytest.param("1.5", 1.5, id="decimal"),
        pytest.param(".5", 0.5, id="no-integer-part"),
        pytest.param("2.", 2.0, id="no-decimal-part"),
        pytest.param("+3", 3.0, id="plus-sign"),
        pytest.param("-1", 0.0, id="negative"),
        pytest.param("-1.5", 0.0, id="negative-decimal"),
        pytest.param("-inf", 0.0, id="negative-infinity"),
        pytest.param("-" + "9" * 5000, 0.0, id="huge-negative"),
        pytest.param("999999999999", 999999999999.0, id="large"),
        pytest.param("9" * 5000, float("inf"), id="huge"),
        pytest.param("inf", float("inf"), id="inf"),
        pytest.param("Infinity", float("inf"), id="infinity"),
    ],
)
def test_parse_retry_after_number(value: str, delay: float) -> None:
    assert parse_retry_after(value) == delay


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", id="imf-fixdate"),
        pytest.param("Sunday, 06-Nov-94 08:49:37 GMT", id="rfc-850"),
        pytest.param("Sun Nov  6 08:49:37 1994", id="asctime"),
        pytest.param("Sun, 06 Nov 1994 10:49:37 +0200", id="positive-offset"),
        pytest.param("Sun, 06 Nov 1994 03:49:37 -0500", id="negative-offset"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 -0000", id="unknown-offset"),
        pytest.param("Sun, 06 Nov 1994 08:49:37", id="no-offset"),
    ],
)
def test_parse_retry_after_date(value: str) -> None:
    assert parse_retry_after(value, now=DATE - 30) == 30.0


def test_parse_retry_after_date_in_the_past() -> None:
    assert parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT", now=DATE + 30) == 0.0


def test_parse_retry_after_date_now() -> None:
    assert parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT", now=DATE) == 0.0


def test_parse_retry_after_date_uses_current_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("persista.http.retry.time.time", lambda: DATE - 5)

    assert parse_retry_after("Sun, 06 Nov 1994 08:49:37 GMT") == 5.0


def test_parse_retry_after_far_future_date() -> None:
    assert parse_retry_after("Fri, 31 Dec 9999 23:59:59 -2300", now=0.0) == 253402383599.0


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="no-header"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("soon", id="word"),
        pytest.param("nan", id="nan"),
        pytest.param("-nan", id="negative-nan"),
        pytest.param("1e3", id="exponent"),
        pytest.param("1_000", id="underscore"),
        pytest.param("5 seconds", id="unit"),
        pytest.param("-", id="sign-only"),
        pytest.param("1, 2", id="repeated-header"),
        # ARABIC-INDIC DIGIT ONE.
        pytest.param(chr(1633), id="non-ascii-digit"),
        pytest.param("Sun, 99 Nov 1994 08:49:37 GMT", id="invalid-day"),
        pytest.param("Sun, 06 Nov 99999999999999999999 08:49:37 GMT", id="huge-year"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 +999999999999999", id="huge-offset"),
        pytest.param(chr(0), id="nul"),
    ],
)
def test_parse_retry_after_invalid(value: str | None) -> None:
    assert parse_retry_after(value) is None


#################################
#     Tests for RetryPolicy     #
#################################


def test_retry_policy_default_max_retries() -> None:
    assert RetryPolicy().max_retries == 3


def test_retry_policy_default_retry_status_codes() -> None:
    assert RetryPolicy().retry_status_codes == frozenset({429, 500, 502, 503, 504})


def test_retry_policy_default_retry_methods() -> None:
    assert RetryPolicy().retry_methods == frozenset(
        {"DELETE", "GET", "HEAD", "OPTIONS", "PUT", "TRACE"}
    )


def test_retry_policy_default_max_delay() -> None:
    assert RetryPolicy().max_delay == 60.0


def test_retry_policy_default_constants() -> None:
    policy = RetryPolicy()

    assert (policy.retry_status_codes, policy.retry_methods, policy.max_delay) == (
        DEFAULT_RETRY_STATUS_CODES,
        IDEMPOTENT_METHODS,
        DEFAULT_MAX_DELAY,
    )


def test_retry_policy_copies_collections() -> None:
    codes, methods = [500], ["post"]
    policy = RetryPolicy(retry_status_codes=codes, retry_methods=methods)

    codes.append(501)
    methods.append("GET")

    assert (policy.retry_status_codes, policy.retry_methods) == ({500}, {"POST"})


def test_retry_policy_max_delay_is_float() -> None:
    assert isinstance(RetryPolicy(max_delay=5).max_delay, float)


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        pytest.param(
            {"max_retries": -1}, ValueError, r"max_retries must be a non-negative", id="retries"
        ),
        pytest.param(
            {"max_delay": -1}, ValueError, r"max_delay must be a finite non-negative", id="delay"
        ),
        pytest.param({"retry_status_codes": [99]}, ValueError, r"between 100 and 599", id="status"),
        pytest.param(
            {"retry_methods": "GET"}, TypeError, r"retry_methods must be a collection", id="method"
        ),
    ],
)
def test_retry_policy_invalid_argument(
    kwargs: dict[str, Any], error: type[Exception], match: str
) -> None:
    with pytest.raises(error, match=match):
        RetryPolicy(**kwargs)


def test_retry_policy_repr() -> None:
    policy = RetryPolicy(retry_status_codes=[503, 429], retry_methods=["put", "get"])

    assert repr(policy) == (
        "RetryPolicy(max_retries=3, retry_status_codes=[429, 503], "
        "retry_methods=['GET', 'PUT'], max_delay=60.0)"
    )


def test_retry_policy_replace_nothing() -> None:
    policy = RetryPolicy()

    assert policy.replace() is policy


def test_retry_policy_replace_all() -> None:
    policy = RetryPolicy(retry_methods=["POST"], max_delay=5).replace(
        max_retries=0, retry_status_codes=[]
    )

    assert repr(policy) == (
        "RetryPolicy(max_retries=0, retry_status_codes=[], retry_methods=['POST'], max_delay=5.0)"
    )


def test_retry_policy_replace_keeps_max_retries() -> None:
    assert RetryPolicy(max_retries=7).replace(retry_status_codes=[500]).max_retries == 7


def test_retry_policy_replace_keeps_retry_status_codes() -> None:
    policy = RetryPolicy(retry_status_codes=[418]).replace(max_retries=1)

    assert policy.retry_status_codes == {418}


def test_retry_policy_replace_does_not_mutate() -> None:
    policy = RetryPolicy()

    policy.replace(max_retries=9)

    assert policy.max_retries == 3


def test_retry_policy_replace_invalid() -> None:
    with pytest.raises(ValueError, match=r"max_retries must be a non-negative"):
        RetryPolicy().replace(max_retries=-1)


@pytest.mark.parametrize("method", ["GET", "get", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"])
def test_retry_policy_get_max_retries_idempotent(method: str) -> None:
    assert RetryPolicy(max_retries=5).get_max_retries(method) == 5


@pytest.mark.parametrize("method", ["POST", "post", "PATCH", "CONNECT", "UNKNOWN"])
def test_retry_policy_get_max_retries_not_idempotent(method: str) -> None:
    assert RetryPolicy().get_max_retries(method) == 0


def test_retry_policy_get_max_retries_added_method() -> None:
    policy = RetryPolicy(retry_methods=IDEMPOTENT_METHODS | {"post"})

    assert policy.get_max_retries("POST") == 3


def test_retry_policy_get_max_retries_replaced_methods() -> None:
    assert RetryPolicy(retry_methods=["POST"]).get_max_retries("GET") == 0


@pytest.mark.parametrize(
    ("attempt", "delay"), [(1, 1.0), (2, 2.0), (3, 4.0), (6, 32.0), (7, 60.0), (100000, 60.0)]
)
def test_retry_policy_get_delay_backoff(attempt: int, delay: float) -> None:
    assert RetryPolicy().get_delay(attempt) == delay


@pytest.mark.parametrize(
    ("retry_after", "delay"),
    [
        pytest.param("0", 0.0, id="zero"),
        pytest.param("5", 5.0, id="seconds"),
        pytest.param("-1", 0.0, id="negative"),
        pytest.param("61", 60.0, id="above-maximum"),
        pytest.param("9" * 5000, 60.0, id="huge"),
        pytest.param("Fri, 31 Dec 9999 23:59:59 GMT", 60.0, id="future-date"),
        pytest.param("Sun, 06 Nov 1994 08:49:37 GMT", 0.0, id="past-date"),
        pytest.param("nan", 2.0, id="nan"),
        pytest.param("soon", 2.0, id="garbage"),
    ],
)
def test_retry_policy_get_delay_retry_after(retry_after: str, delay: float) -> None:
    assert RetryPolicy().get_delay(2, retry_after=retry_after) == delay


@pytest.mark.parametrize("retry_after", [None, "100"])
def test_retry_policy_get_delay_zero_max_delay(retry_after: str | None) -> None:
    assert RetryPolicy(max_delay=0).get_delay(3, retry_after=retry_after) == 0.0


def test_retry_policy_get_delay_huge_attempt_large_maximum() -> None:
    # 2 ** 1023, the largest power of 2 that is a float.
    assert RetryPolicy(max_delay=1e308).get_delay(10**6) == 8.98846567431158e307


@pytest.mark.parametrize("attempt", [0, -1])
def test_retry_policy_get_delay_invalid_attempt(attempt: int) -> None:
    with pytest.raises(ValueError, match=r"attempt must be a positive integer"):
        RetryPolicy().get_delay(attempt)


##########################################
#     Tests for validate_max_retries     #
##########################################


@pytest.mark.parametrize("max_retries", [0, 1, 1000])
def test_validate_max_retries_valid(max_retries: int) -> None:
    validate_max_retries(max_retries)


@pytest.mark.parametrize("max_retries", [1.0, "1", None, True])
def test_validate_max_retries_wrong_type(max_retries: Any) -> None:
    with pytest.raises(TypeError, match=r"max_retries must be an int"):
        validate_max_retries(max_retries)


def test_validate_max_retries_negative() -> None:
    with pytest.raises(ValueError, match=r"max_retries must be a non-negative integer, got -1"):
        validate_max_retries(-1)


########################################
#     Tests for validate_max_delay     #
########################################


@pytest.mark.parametrize("max_delay", [0, 0.0, 1.5, 86400, Fraction(1, 2)])
def test_validate_max_delay_valid(max_delay: float) -> None:
    validate_max_delay(max_delay)


@pytest.mark.parametrize("max_delay", ["1", None, True, 1j])
def test_validate_max_delay_wrong_type(max_delay: Any) -> None:
    with pytest.raises(TypeError, match=r"max_delay must be a number"):
        validate_max_delay(max_delay)


@pytest.mark.parametrize("max_delay", [-0.1, float("inf"), float("-inf"), float("nan")])
def test_validate_max_delay_invalid_value(max_delay: float) -> None:
    with pytest.raises(ValueError, match=r"max_delay must be a finite non-negative number"):
        validate_max_delay(max_delay)


############################################
#     Tests for normalize_status_codes     #
############################################


def test_normalize_status_codes() -> None:
    assert normalize_status_codes([503, 429, 503]) == frozenset({429, 503})


@pytest.mark.parametrize("codes", [[], set(), ()])
def test_normalize_status_codes_empty(codes: Any) -> None:
    assert normalize_status_codes(codes) == frozenset()


def test_normalize_status_codes_bounds() -> None:
    assert normalize_status_codes(iter([100, 599])) == frozenset({100, 599})


@pytest.mark.parametrize("codes", [500, None])
def test_normalize_status_codes_not_iterable(codes: Any) -> None:
    with pytest.raises(TypeError, match=r"retry_status_codes must be a collection of int, got"):
        normalize_status_codes(codes)


@pytest.mark.parametrize("codes", ["500", ["500"], [500.0], [True], [None]])
def test_normalize_status_codes_wrong_item(codes: Any) -> None:
    with pytest.raises(TypeError, match=r"got the item"):
        normalize_status_codes(codes)


@pytest.mark.parametrize("code", [-1, 0, 99, 600])
def test_normalize_status_codes_out_of_range(code: int) -> None:
    with pytest.raises(ValueError, match=r"An HTTP status code must be between 100 and 599"):
        normalize_status_codes([code])


#######################################
#     Tests for normalize_methods     #
#######################################


def test_normalize_methods() -> None:
    assert normalize_methods(["get", "Post", "GET"], name="x") == frozenset({"GET", "POST"})


def test_normalize_methods_empty() -> None:
    assert normalize_methods([], name="x") == frozenset()


def test_normalize_methods_iterator() -> None:
    assert normalize_methods(iter(["get"]), name="x") == frozenset({"GET"})


@pytest.mark.parametrize("methods", ["GET", None, 1])
def test_normalize_methods_not_a_collection(methods: Any) -> None:
    with pytest.raises(TypeError, match=r"my_methods must be a collection of str, got"):
        normalize_methods(methods, name="my_methods")


@pytest.mark.parametrize("methods", [[b"GET"], [None]])
def test_normalize_methods_wrong_item(methods: Any) -> None:
    with pytest.raises(TypeError, match=r"my_methods must be a collection of str, got the item"):
        normalize_methods(methods, name="my_methods")
