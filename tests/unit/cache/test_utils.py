from __future__ import annotations

import logging

import pytest

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
        pass

    with pytest.raises(TypeError):
        make_key("func", (Custom(),), {})


def test_make_key_non_json_serializable_argument_ignored() -> None:
    class Custom:
        pass

    assert make_key("func", (Custom(),), {}, ignore_non_serializable=True) == make_key(
        "func", (), {}, ignore_non_serializable=True
    )


def test_make_key_non_json_serializable_kwarg_ignored() -> None:
    class Custom:
        pass

    assert make_key(
        "func", (), {"a": 1, "obj": Custom()}, ignore_non_serializable=True
    ) == make_key("func", (), {"a": 1}, ignore_non_serializable=True)


def test_make_key_ignore_non_serializable_keeps_serializable_args() -> None:
    assert make_key("func", (1, 2), {}, ignore_non_serializable=True) == make_key(
        "func", (1, 2), {}
    )


def test_make_key_ignore_non_serializable_different_serializable_values() -> None:
    class Custom:
        pass

    assert make_key("func", (1, Custom()), {}, ignore_non_serializable=True) != make_key(
        "func", (2, Custom()), {}, ignore_non_serializable=True
    )


def test_make_key_ignore_non_serializable_default_false() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        make_key("func", (), {"obj": Custom()})
