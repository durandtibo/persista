from __future__ import annotations

import logging

from persista.cache.utils import make_key

logger = logging.getLogger(__name__)


##########################
#     make_key           #
##########################


def test_make_key_returns_string() -> None:
    assert isinstance(make_key("func", (1, 2), {}), str)


def test_make_key_deterministic() -> None:
    assert make_key("func", (1, 2), {"a": 1}) == make_key("func", (1, 2), {"a": 1})


def test_make_key_kwargs_order_independent() -> None:
    assert make_key("func", (), {"a": 1, "b": 2}) == make_key("func", (), {"b": 2, "a": 1})


def test_make_key_different_func_name() -> None:
    assert make_key("func1", (1,), {}) != make_key("func2", (1,), {})


def test_make_key_different_args() -> None:
    assert make_key("func", (1,), {}) != make_key("func", (2,), {})


def test_make_key_different_kwargs() -> None:
    assert make_key("func", (), {"a": 1}) != make_key("func", (), {"a": 2})


def test_make_key_args_vs_kwargs_distinct() -> None:
    assert make_key("func", (1,), {}) != make_key("func", (), {"a": 1})


def test_make_key_non_json_serializable_argument() -> None:
    class Custom:
        def __str__(self) -> str:
            return "custom"

    # falls back to str() via json.dumps(default=str), so this must not raise
    key = make_key("func", (Custom(),), {})
    assert isinstance(key, str)
