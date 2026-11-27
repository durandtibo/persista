from __future__ import annotations

import functools
import logging
import pickle
import threading
from typing import TYPE_CHECKING

import pytest

from persista.cache.utils import (
    is_json_serializable,
    is_picklable,
    make_call_key,
    make_json_key,
    make_key,
    make_pickle_key,
    split_get_many,
    split_try_get_many,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


#########################
#     make_json_key     #
#########################


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


def test_make_json_key_ignore_non_serializable_positional_argument_raises() -> None:
    with pytest.raises(TypeError, match=r"not JSON serializable"):
        make_json_key("func", (object(),), {}, ignore_non_serializable=True)


def test_make_json_key_ignore_non_serializable_unhashable_positional_argument_raises() -> None:
    with pytest.raises(TypeError, match=r"not JSON serializable"):
        make_json_key("func", ([object()],), {}, ignore_non_serializable=True)


def test_make_json_key_non_json_serializable_kwarg_value_ignored() -> None:
    assert make_json_key(
        "func", (), {"a": 1, "obj": object()}, ignore_non_serializable=True
    ) == make_json_key("func", (), {"a": 1, "obj": object()}, ignore_non_serializable=True)


def test_make_json_key_ignored_kwarg_name_stays_in_key() -> None:
    assert make_json_key(
        "func", (), {"a": object()}, ignore_non_serializable=True
    ) != make_json_key("func", (), {"b": object()}, ignore_non_serializable=True)


def test_make_json_key_ignored_kwarg_differs_from_absent_kwarg() -> None:
    assert make_json_key(
        "func", (), {"a": 1, "obj": object()}, ignore_non_serializable=True
    ) != make_json_key("func", (), {"a": 1}, ignore_non_serializable=True)


def test_make_json_key_ignored_kwarg_differs_from_none_value() -> None:
    assert make_json_key("func", (), {"obj": object()}, ignore_non_serializable=True) != (
        make_json_key("func", (), {"obj": None}, ignore_non_serializable=True)
    )


def test_make_json_key_ignored_kwargs_order_independent() -> None:
    assert make_json_key(
        "func", (), {"a": object(), "b": object()}, ignore_non_serializable=True
    ) == make_json_key("func", (), {"b": object(), "a": object()}, ignore_non_serializable=True)


def test_make_json_key_ignore_non_serializable_does_not_mutate_kwargs() -> None:
    obj = object()
    kwargs = {"a": 1, "obj": obj}
    make_json_key("func", (), kwargs, ignore_non_serializable=True)
    assert kwargs == {"a": 1, "obj": obj}


def test_make_json_key_ignore_non_serializable_keeps_serializable_args() -> None:
    assert make_json_key("func", (1, 2), {}, ignore_non_serializable=True) == make_json_key(
        "func", (1, 2), {}
    )


def test_make_json_key_ignore_non_serializable_different_serializable_values() -> None:
    assert make_json_key(
        "func", (1,), {"obj": object()}, ignore_non_serializable=True
    ) != make_json_key("func", (2,), {"obj": object()}, ignore_non_serializable=True)


def test_make_json_key_ignore_non_serializable_default_false() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        make_json_key("func", (), {"obj": Custom()})


def test_make_json_key_json_serializable_unhashable_argument() -> None:
    assert make_json_key("func", ([1, 2],), {}) == make_json_key("func", ([1, 2],), {})


def test_make_json_key_non_json_serializable_unhashable_kwarg_ignored() -> None:
    assert make_json_key(
        "func", (), {"obj": {"x": object()}}, ignore_non_serializable=True
    ) == make_json_key("func", (), {"obj": object()}, ignore_non_serializable=True)


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


def test_make_pickle_key_ignore_non_serializable_positional_argument_raises() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError), match=r"pickle"):
        make_pickle_key("func", (threading.Lock(),), {}, ignore_non_serializable=True)


def test_make_pickle_key_non_picklable_kwarg_value_ignored() -> None:
    assert make_pickle_key(
        "func", (), {"a": 1, "obj": lambda x: x}, ignore_non_serializable=True
    ) == make_pickle_key(
        "func", (), {"a": 1, "obj": threading.Lock()}, ignore_non_serializable=True
    )


def test_make_pickle_key_ignored_kwarg_name_stays_in_key() -> None:
    assert make_pickle_key(
        "func", (), {"a": lambda x: x}, ignore_non_serializable=True
    ) != make_pickle_key("func", (), {"b": lambda x: x}, ignore_non_serializable=True)


def test_make_pickle_key_ignored_kwarg_differs_from_absent_kwarg() -> None:
    assert make_pickle_key(
        "func", (), {"a": 1, "obj": lambda x: x}, ignore_non_serializable=True
    ) != make_pickle_key("func", (), {"a": 1}, ignore_non_serializable=True)


def test_make_pickle_key_ignore_non_serializable_does_not_mutate_kwargs() -> None:
    lock = threading.Lock()
    kwargs = {"a": 1, "obj": lock}
    make_pickle_key("func", (), kwargs, ignore_non_serializable=True)
    assert kwargs == {"a": 1, "obj": lock}


def test_make_pickle_key_ignore_non_serializable_keeps_serializable_args() -> None:
    assert make_pickle_key("func", (1, 2), {}, ignore_non_serializable=True) == make_pickle_key(
        "func", (1, 2), {}
    )


def test_make_pickle_key_ignore_non_serializable_default_false() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError)):
        make_pickle_key("func", (), {"obj": lambda x: x})


def test_make_pickle_key_ignore_non_serializable_unhashable_positional_argument_raises() -> None:
    with pytest.raises((pickle.PicklingError, TypeError, AttributeError), match=r"pickle"):
        make_pickle_key("func", ([threading.Lock()],), {}, ignore_non_serializable=True)


def test_make_pickle_key_picklable_unhashable_argument() -> None:
    assert make_pickle_key("func", ([1, 2],), {}) == make_pickle_key("func", ([1, 2],), {})


####################
#     make_key     #
####################


def test_make_key_default_strategy_is_json() -> None:
    assert make_key("func", (1, 2), {}) == make_json_key("func", (1, 2), {})


def test_make_key_strategy_json() -> None:
    assert make_key("func", (1, 2), {}, strategy="json") == make_json_key("func", (1, 2), {})


def test_make_key_strategy_pickle() -> None:
    assert make_key("func", (1, 2), {}, strategy="pickle") == make_pickle_key("func", (1, 2), {})


def test_make_key_strategy_json_supports_ignore_non_serializable() -> None:
    assert make_key(
        "func", (), {"a": object()}, strategy="json", ignore_non_serializable=True
    ) == make_json_key("func", (), {"a": object()}, ignore_non_serializable=True)


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


################################
#     is_json_serializable     #
################################


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(1, True, id="hashable-serializable-int"),
        pytest.param("abc", True, id="hashable-serializable-str"),
        pytest.param((1, 2), True, id="hashable-serializable-tuple"),
        pytest.param(None, True, id="hashable-serializable-none"),
        pytest.param(object(), False, id="hashable-non-serializable-object"),
        pytest.param([1, 2], True, id="unhashable-serializable-list"),
        pytest.param({"a": 1}, True, id="unhashable-serializable-dict"),
        pytest.param([object()], False, id="unhashable-non-serializable-list"),
        pytest.param({"a": object()}, False, id="unhashable-non-serializable-dict"),
    ],
)
def test_is_json_serializable(value: object, expected: bool) -> None:
    assert is_json_serializable(value) is expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param((1, 2), id="hashable"),
        pytest.param([1, 2], id="unhashable"),
    ],
)
def test_is_json_serializable_repeated_calls_are_consistent(value: object) -> None:
    assert is_json_serializable(value) is is_json_serializable(value)


########################
#     is_picklable     #
########################


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(1, True, id="hashable-picklable-int"),
        pytest.param("abc", True, id="hashable-picklable-str"),
        pytest.param((1, 2), True, id="hashable-picklable-tuple"),
        pytest.param({1, 2, 3}, True, id="hashable-picklable-set"),
        pytest.param(lambda x: x, False, id="hashable-non-picklable-lambda"),
        pytest.param([1, 2], True, id="unhashable-picklable-list"),
        pytest.param({"a": 1}, True, id="unhashable-picklable-dict"),
        pytest.param([lambda x: x], False, id="unhashable-non-picklable-list"),
        pytest.param({"a": lambda x: x}, False, id="unhashable-non-picklable-dict"),
    ],
)
def test_is_picklable(value: object, expected: bool) -> None:
    assert is_picklable(value) is expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param((1, 2), id="hashable"),
        pytest.param([1, 2], id="unhashable"),
    ],
)
def test_is_picklable_repeated_calls_are_consistent(value: object) -> None:
    assert is_picklable(value) is is_picklable(value)


#########################
#     make_call_key     #
#########################


def _load(x: int = 0) -> int:
    return x


def _function_of_module(module: str | None) -> Callable[[], None]:
    """Return a function whose ``__module__`` is ``module``."""

    def load() -> None:
        pass

    load.__module__ = module
    return load


def test_make_call_key_uses_module_and_qualified_name() -> None:
    assert make_call_key(_load, (1,), {"y": 2}) == make_key(f"{__name__}:_load", (1,), {"y": 2})


def test_make_call_key_same_qualname_different_modules() -> None:
    assert make_call_key(_function_of_module("a"), (), {}) != make_call_key(
        _function_of_module("b"), (), {}
    )


def test_make_call_key_same_module_and_qualname() -> None:
    assert make_call_key(_function_of_module("a"), (), {}) == make_call_key(
        _function_of_module("a"), (), {}
    )


def test_make_call_key_without_module() -> None:
    func = _function_of_module(None)
    assert make_call_key(func, (), {}) == make_key(f":{func.__qualname__}", (), {})


def test_make_call_key_without_qualname_uses_repr() -> None:
    func = functools.partial(_load, 1)
    assert make_call_key(func, (), {}) == make_key(f"functools:{func!r}", (), {})


def test_make_call_key_different_args() -> None:
    assert make_call_key(_load, (1,), {}) != make_call_key(_load, (2,), {})


def test_make_call_key_pickle_strategy() -> None:
    assert make_call_key(_load, (1,), {}, strategy="pickle") == make_pickle_key(
        f"{__name__}:_load", (1,), {}
    )


def test_make_call_key_unknown_strategy() -> None:
    with pytest.raises(ValueError, match=r"Unknown strategy: 'yaml'"):
        make_call_key(_load, (), {}, strategy="yaml")


def test_make_call_key_ignore_non_serializable_kwarg() -> None:
    assert make_call_key(_load, (), {"x": object()}, ignore_non_serializable=True) == make_call_key(
        _load, (), {"x": object()}, ignore_non_serializable=True
    )


def test_make_call_key_ignore_non_serializable_positional_argument_raises() -> None:
    with pytest.raises(TypeError, match=r"not JSON serializable"):
        make_call_key(_load, (object(),), {}, ignore_non_serializable=True)


########################
#     split_get_many     #
########################


def test_split_get_many_all_present() -> None:
    assert split_get_many(["a", "b"], {"a": 1, "b": 2}, None) == (["a", "b"], [])


def test_split_get_many_all_missing() -> None:
    assert split_get_many(["a", "b"], {"a": None, "b": None}, None) == ([], ["a", "b"])


def test_split_get_many_mixed() -> None:
    assert split_get_many(["a", "b", "c"], {"a": 1, "b": None, "c": 3}, None) == (
        ["a", "c"],
        ["b"],
    )


def test_split_get_many_empty() -> None:
    assert split_get_many([], {}, None) == ([], [])


def test_split_get_many_default_sentinel() -> None:
    sentinel = object()
    assert split_get_many(["a", "b"], {"a": None, "b": sentinel}, sentinel) == (["a"], ["b"])


############################
#     split_try_get_many     #
############################


def test_split_try_get_many_all_present() -> None:
    assert split_try_get_many(["a", "b"], {"a": 1, "b": 2}) == (["a", "b"], [])


def test_split_try_get_many_all_missing() -> None:
    assert split_try_get_many(["a", "b"], {}) == ([], ["a", "b"])


def test_split_try_get_many_mixed() -> None:
    assert split_try_get_many(["a", "b", "c"], {"a": 1, "c": 3}) == (["a", "c"], ["b"])


def test_split_try_get_many_empty() -> None:
    assert split_try_get_many([], {}) == ([], [])
