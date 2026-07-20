from __future__ import annotations

import logging
import pickle

import pytest

from persista.cache.utils import make_json_key, make_key, make_pickle_key

logger = logging.getLogger(__name__)


####################
#     make_json_key     #
####################


def test_make_json_key_returns_string() -> None:
    assert isinstance(make_json_key("func", (1, 2), {}), str)


def test_make_json_key_deterministic() -> None:
    assert make_json_key("func", (1, 2), {"a": 1}) == make_json_key("func", (1, 2), {"a": 1})


def test_make_json_key_kwargs_order_independent() -> None:
    assert make_json_key("func", (), {"a": 1, "b": 2}) == make_json_key(
        "func", (), {"b": 2, "a": 1}
    )


def test_make_json_key_different_func_name() -> None:
    assert make_json_key("func1", (1,), {}) != make_json_key("func2", (1,), {})


def test_make_json_key_different_args() -> None:
    assert make_json_key("func", (1,), {}) != make_json_key("func", (2,), {})


def test_make_json_key_different_kwargs() -> None:
    assert make_json_key("func", (), {"a": 1}) != make_json_key("func", (), {"a": 2})


def test_make_json_key_args_vs_kwargs_distinct() -> None:
    assert make_json_key("func", (1,), {}) != make_json_key("func", (), {"a": 1})


def test_make_json_key_non_json_serializable_argument() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        make_json_key("func", (Custom(),), {})


def test_make_json_key_non_json_serializable_argument_ignored() -> None:
    class Custom:
        pass

    assert make_json_key("func", (Custom(),), {}, ignore_non_serializable=True) == make_json_key(
        "func", (), {}, ignore_non_serializable=True
    )


def test_make_json_key_non_json_serializable_kwarg_ignored() -> None:
    class Custom:
        pass

    assert make_json_key(
        "func", (), {"a": 1, "obj": Custom()}, ignore_non_serializable=True
    ) == make_json_key("func", (), {"a": 1}, ignore_non_serializable=True)


def test_make_json_key_ignore_non_serializable_keeps_serializable_args() -> None:
    assert make_json_key("func", (1, 2), {}, ignore_non_serializable=True) == make_json_key(
        "func", (1, 2), {}
    )


def test_make_json_key_ignore_non_serializable_different_serializable_values() -> None:
    class Custom:
        pass

    assert make_json_key("func", (1, Custom()), {}, ignore_non_serializable=True) != make_json_key(
        "func", (2, Custom()), {}, ignore_non_serializable=True
    )


def test_make_json_key_ignore_non_serializable_default_false() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        make_json_key("func", (), {"obj": Custom()})


###########################
#     make_pickle_key     #
###########################


def test_make_pickle_key_returns_string() -> None:
    assert isinstance(make_pickle_key("func", (1, 2), {}), str)


def test_make_pickle_key_deterministic() -> None:
    assert make_pickle_key("func", (1, 2), {"a": 1}) == make_pickle_key("func", (1, 2), {"a": 1})


def test_make_pickle_key_kwargs_order_independent() -> None:
    assert make_pickle_key("func", (), {"a": 1, "b": 2}) == make_pickle_key(
        "func", (), {"b": 2, "a": 1}
    )


def test_make_pickle_key_different_func_name() -> None:
    assert make_pickle_key("func1", (1,), {}) != make_pickle_key("func2", (1,), {})


def test_make_pickle_key_different_args() -> None:
    assert make_pickle_key("func", (1,), {}) != make_pickle_key("func", (2,), {})


def test_make_pickle_key_different_kwargs() -> None:
    assert make_pickle_key("func", (), {"a": 1}) != make_pickle_key("func", (), {"a": 2})


def test_make_pickle_key_args_vs_kwargs_distinct() -> None:
    assert make_pickle_key("func", (1,), {}) != make_pickle_key("func", (), {"a": 1})


def test_make_pickle_key_supports_non_json_serializable_argument() -> None:
    assert make_pickle_key("func", ({1, 2, 3},), {}) == make_pickle_key("func", ({1, 2, 3},), {})


def test_make_pickle_key_non_picklable_argument() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError)):
        make_pickle_key("func", (lambda x: x,), {})


def test_make_pickle_key_non_picklable_argument_ignored() -> None:
    assert make_pickle_key(
        "func", (lambda x: x,), {}, ignore_non_serializable=True
    ) == make_pickle_key("func", (), {}, ignore_non_serializable=True)


def test_make_pickle_key_non_picklable_kwarg_ignored() -> None:
    assert make_pickle_key(
        "func", (), {"a": 1, "obj": lambda x: x}, ignore_non_serializable=True
    ) == make_pickle_key("func", (), {"a": 1}, ignore_non_serializable=True)


def test_make_pickle_key_ignore_non_serializable_keeps_serializable_args() -> None:
    assert make_pickle_key("func", (1, 2), {}, ignore_non_serializable=True) == make_pickle_key(
        "func", (1, 2), {}
    )


def test_make_pickle_key_ignore_non_serializable_default_false() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError)):
        make_pickle_key("func", (), {"obj": lambda x: x})


####################
#     make_key     #
####################


def test_make_key_default_strategy_is_pickle() -> None:
    assert make_key("func", (1, 2), {}) == make_pickle_key("func", (1, 2), {})


def test_make_key_strategy_json() -> None:
    assert make_key("func", (1, 2), {}, strategy="json") == make_json_key("func", (1, 2), {})


def test_make_key_strategy_pickle() -> None:
    assert make_key("func", (1, 2), {}, strategy="pickle") == make_pickle_key("func", (1, 2), {})


def test_make_key_strategy_json_supports_ignore_non_serializable() -> None:
    class Custom:
        pass

    assert make_key(
        "func", (Custom(),), {}, strategy="json", ignore_non_serializable=True
    ) == make_key("func", (), {}, strategy="json", ignore_non_serializable=True)


def test_make_key_strategy_json_non_serializable_raises() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        make_key("func", (Custom(),), {}, strategy="json")


def test_make_key_strategy_pickle_supports_non_json_serializable_argument() -> None:
    assert make_key("func", ({1, 2, 3},), {}, strategy="pickle") == make_key(
        "func", ({1, 2, 3},), {}, strategy="pickle"
    )


def test_make_key_strategy_pickle_non_picklable_raises() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError)):
        make_key("func", (lambda x: x,), {}, strategy="pickle")


def test_make_key_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="Unknown strategy"):
        make_key("func", (), {}, strategy="unknown")
