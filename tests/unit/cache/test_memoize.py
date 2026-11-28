from __future__ import annotations

import functools
import inspect
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from persista.cache.cache import Cache
from persista.cache.memoize import (
    _bind_arguments,
    build_key_function,
    check_memoize_options,
    memoize_with,
)
from persista.utils.canonical import hash_canonical

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


@pytest.fixture
def cache() -> Generator[Cache]:
    with Cache() as cache:
        yield cache


def add(x: object, y: object = 0) -> None:
    del x, y


def collect(a: object, *args: object, b: object = 2, **kwargs: object) -> None:
    del a, args, b, kwargs


def positional(a: object = 0, /, **kwargs: object) -> None:
    del a, kwargs


class Loader:
    def load(self, x: int) -> int:
        return x

    @classmethod
    def build(cls, x: int) -> int:
        return x

    @staticmethod
    def parse(x: int) -> int:
        return x


class Items(list):
    def first(self) -> object:
        return self[0]


class CallableObject:
    def __call__(self) -> None:
        pass


def passthrough(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


########################################
#     Tests for build_key_function     #
########################################


def test_build_key_function_value() -> None:
    assert build_key_function(add)((1,), {}) == hash_canonical((__name__, "add", {"x": 1, "y": 0}))


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        pytest.param((1, 0), {}, id="positional-default"),
        pytest.param((), {"x": 1}, id="keyword"),
        pytest.param((), {"y": 0, "x": 1}, id="keyword-order"),
        pytest.param((1,), {"y": 0}, id="mixed"),
    ],
)
def test_build_key_function_same_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    make_key = build_key_function(add)
    assert make_key(args, kwargs) == make_key((1,), {})


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param([1, 2], (1, 2), id="list-tuple"),
        pytest.param(1, "1", id="int-str"),
        pytest.param(1, True, id="int-bool"),
        pytest.param(1, 1.0, id="int-float"),
        pytest.param({1}, frozenset({1}), id="set-frozenset"),
        pytest.param({1: "a"}, {"1": "a"}, id="dict-keys"),
        pytest.param(1, 2, id="values"),
    ],
)
def test_build_key_function_different_arguments(first: object, second: object) -> None:
    make_key = build_key_function(add)
    assert make_key((first,), {}) != make_key((second,), {})


def test_build_key_function_argument_position() -> None:
    make_key = build_key_function(add)
    assert make_key((1, 2), {}) != make_key((2, 1), {})


def test_build_key_function_set_order() -> None:
    make_key = build_key_function(add)
    assert make_key(({0, 8},), {}) == make_key(({8, 0},), {})


def test_build_key_function_equal_objects_not_identical() -> None:
    make_key = build_key_function(add)
    item = "".join(["a", "b"])
    assert make_key(([item, item],), {}) == make_key((["ab", "".join(["a", "b"])],), {})


def test_build_key_function_does_not_mutate_arguments() -> None:
    kwargs = {"y": 2, "x": 1}
    build_key_function(add)((), kwargs)
    assert list(kwargs.items()) == [("y", 2), ("x", 1)]


def test_build_key_function_var_arguments() -> None:
    assert build_key_function(collect)((1, 3), {"c": 4}) == hash_canonical(
        (__name__, "collect", {"a": 1, "args": (3,), "b": 2, "kwargs": {"c": 4}})
    )


def test_build_key_function_empty_var_arguments() -> None:
    assert build_key_function(collect)((1,), {}) == hash_canonical(
        (__name__, "collect", {"a": 1, "args": (), "b": 2, "kwargs": {}})
    )


def test_build_key_function_var_keyword_order() -> None:
    make_key = build_key_function(collect)
    assert make_key((1,), {"c": 3, "d": 4}) == make_key((1,), {"d": 4, "c": 3})


def test_build_key_function_var_positional_order() -> None:
    make_key = build_key_function(collect)
    assert make_key((1, 3, 4), {}) != make_key((1, 4, 3), {})


def test_build_key_function_var_positional_differs_from_keyword() -> None:
    make_key = build_key_function(collect)
    assert make_key((1, 3), {}) != make_key((1,), {"b": 3})


def test_build_key_function_positional_only_name_in_var_keyword() -> None:
    assert build_key_function(positional)((1,), {"a": 2}) == hash_canonical(
        (__name__, "positional", {"a": 1, "kwargs": {"a": 2}})
    )


def test_build_key_function_omitted_positional_only_name_in_var_keyword() -> None:
    assert build_key_function(positional)((), {"a": 2}) == hash_canonical(
        (__name__, "positional", {"a": 0, "kwargs": {"a": 2}})
    )


@pytest.mark.parametrize(
    ("args", "kwargs", "message"),
    [
        pytest.param((), {}, r"missing a required argument: 'x'", id="missing"),
        pytest.param((1, 2, 3), {}, r"too many positional arguments", id="too-many"),
        pytest.param((1,), {"z": 2}, r"unexpected keyword argument 'z'", id="unknown"),
        pytest.param((1,), {"x": 2}, r"multiple values for argument 'x'", id="twice"),
    ],
)
def test_build_key_function_binding_error(
    args: tuple[Any, ...], kwargs: dict[str, Any], message: str
) -> None:
    make_key = build_key_function(add)
    with pytest.raises(TypeError, match=message):
        make_key(args, kwargs)


def test_build_key_function_argument_not_encodable() -> None:
    make_key = build_key_function(add)
    with pytest.raises(
        TypeError,
        match=r"Cannot compute the cache key of a call of add: Cannot encode an object of "
        r"type decimal\.Decimal\. .*ignore=.*key=",
    ):
        make_key((Decimal(1),), {})


def test_build_key_function_equal_argument_of_another_type_not_encodable() -> None:
    make_key = build_key_function(add)
    make_key((1,), {})
    with pytest.raises(TypeError, match=r"Cannot encode an object of type decimal\.Decimal"):
        make_key((Decimal(1),), {})


def test_build_key_function_default_not_encodable() -> None:
    def func(x: int, marker: object = Decimal(0)) -> None:
        del x, marker

    make_key = build_key_function(func)
    with pytest.raises(TypeError, match=r"Cannot compute the cache key"):
        make_key((1,), {})


def test_build_key_function_cycle() -> None:
    value: list[object] = []
    value.append(value)
    make_key = build_key_function(add)
    with pytest.raises(ValueError, match=r"Cannot encode a list that contains itself"):
        make_key((value,), {})


def test_build_key_function_ignore() -> None:
    make_key = build_key_function(add, ignore=["y"])
    assert make_key((1, object()), {}) == make_key((1,), {})


def test_build_key_function_ignore_keeps_other_arguments() -> None:
    make_key = build_key_function(add, ignore=["y"])
    assert make_key((1,), {}) != make_key((2,), {})


def test_build_key_function_ignore_all() -> None:
    make_key = build_key_function(add, ignore=("x", "y"))
    assert make_key((1, 2), {}) == hash_canonical((__name__, "add", {}))


@pytest.mark.parametrize(
    ("name", "args", "kwargs"),
    [
        pytest.param("args", (1, object()), {}, id="var-positional"),
        pytest.param("kwargs", (1,), {"c": object()}, id="var-keyword"),
    ],
)
def test_build_key_function_ignore_var_arguments(
    name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    make_key = build_key_function(collect, ignore=[name])
    assert make_key(args, kwargs) == make_key((1,), {})


@pytest.mark.parametrize("ignore", [["z"], ["x", "z"]])
def test_build_key_function_ignore_unknown_name(ignore: list[str]) -> None:
    with pytest.raises(
        ValueError, match=r"ignore names parameters that add does not have: \['z'\]"
    ):
        build_key_function(add, ignore=ignore)


def test_build_key_function_ignore_name_collected_by_var_keyword() -> None:
    with pytest.raises(ValueError, match=r"does not have: \['client'\]"):
        build_key_function(collect, ignore=["client"])


def test_build_key_function_key() -> None:
    make_key = build_key_function(add, key=lambda x, y=0: f"add:{x}:{y}")
    assert make_key((1,), {"y": 2}) == "add:1:2"


def test_build_key_function_key_error() -> None:
    def key(*args: object, **kwargs: object) -> str:
        msg = f"no key for {args} {kwargs}"
        raise LookupError(msg)

    make_key = build_key_function(add, key=key)
    with pytest.raises(LookupError, match=r"no key"):
        make_key((1,), {})


def test_build_key_function_key_accepts_partial() -> None:
    func = functools.partial(add, 1)
    assert build_key_function(func, key=lambda: "k")((), {}) == "k"


def test_build_key_function_ignore_str() -> None:
    with pytest.raises(TypeError, match=r"ignore must be a collection of parameter names"):
        build_key_function(add, ignore="x")


def test_build_key_function_ignore_and_key() -> None:
    with pytest.raises(ValueError, match=r"ignore and key cannot be used together"):
        build_key_function(add, ignore=["x"], key=str)


def test_build_key_function_method_includes_self() -> None:
    make_key = build_key_function(Loader.load)
    with pytest.raises(TypeError, match=r"Cannot encode an object of type .*Loader"):
        make_key((Loader(), 1), {})


@pytest.mark.parametrize(
    "func",
    [
        pytest.param(Loader().load, id="method"),
        pytest.param(Loader.build, id="classmethod"),
        pytest.param(passthrough(Loader().load), id="wrapped-method"),
    ],
)
def test_build_key_function_bound_method_includes_object(func: Callable[..., Any]) -> None:
    make_key = build_key_function(func)
    with pytest.raises(TypeError, match=r"Cannot compute the cache key"):
        make_key((1,), {})


@pytest.mark.parametrize(
    ("func", "name"),
    [
        pytest.param(Loader().load, "self", id="method"),
        pytest.param(Loader.build, "cls", id="classmethod"),
        pytest.param(passthrough(Loader().load), "self", id="wrapped-method"),
    ],
)
def test_build_key_function_bound_method_ignore_object(func: Callable[..., Any], name: str) -> None:
    make_key = build_key_function(func, ignore=[name])
    assert make_key((1,), {}) != make_key((2,), {})


def test_build_key_function_bound_method_of_list_subclass() -> None:
    make_key = build_key_function(Items([1]).first)
    with pytest.raises(TypeError, match=r"Cannot encode an object of type .*Items"):
        make_key((), {})


def test_build_key_function_staticmethod() -> None:
    assert build_key_function(Loader.parse)((1,), {}) == hash_canonical(
        (__name__, "Loader.parse", {"x": 1})
    )


@pytest.mark.parametrize(
    "func",
    [
        pytest.param({"a": 1}.get, id="dict-method"),
        pytest.param([1].index, id="list-method"),
        pytest.param(int.from_bytes, id="builtin-classmethod"),
    ],
)
def test_build_key_function_builtin_method_of_object(func: Callable[..., Any]) -> None:
    with pytest.raises(TypeError, match=r"a built-in method bound to an object: pass key="):
        build_key_function(func)


def test_build_key_function_builtin_function() -> None:
    assert build_key_function(len)(([1],), {}) == hash_canonical(("builtins", "len", {"obj": [1]}))


@pytest.mark.parametrize(
    "func",
    [
        pytest.param(functools.partial(add, 1), id="partial"),
        pytest.param(CallableObject(), id="callable-object"),
    ],
)
def test_build_key_function_without_qualname(func: Callable[..., Any]) -> None:
    with pytest.raises(TypeError, match=r"has no __qualname__: pass key="):
        build_key_function(func)


def test_build_key_function_without_signature() -> None:
    with pytest.raises(ValueError, match=r"no signature found"):
        build_key_function(dict)


@pytest.mark.parametrize("attribute", ["__module__", "__qualname__"])
def test_build_key_function_depends_on_name(attribute: str) -> None:
    def func() -> None:
        pass

    first = build_key_function(func)((), {})
    setattr(func, attribute, "other")
    assert build_key_function(func)((), {}) != first


def test_build_key_function_without_module() -> None:
    def func() -> None:
        pass

    func.__module__ = None
    assert build_key_function(func)((), {}) == hash_canonical(
        (None, "test_build_key_function_without_module.<locals>.func", {})
    )


#####################################
#     Tests for _bind_arguments     #
#####################################


@pytest.mark.parametrize(
    ("func", "args", "kwargs", "expected"),
    [
        pytest.param(add, (1,), {}, {"x": 1, "y": 0}, id="default"),
        pytest.param(add, (), {"y": 2, "x": 1}, {"x": 1, "y": 2}, id="keywords"),
        pytest.param(
            collect,
            (1, 3),
            {"c": 4},
            {"a": 1, "args": (3,), "b": 2, "kwargs": {"c": 4}},
            id="var-arguments",
        ),
        pytest.param(positional, (), {}, {"a": 0, "kwargs": {}}, id="positional-only-default"),
        pytest.param(
            positional,
            (1,),
            {"a": 2},
            {"a": 1, "kwargs": {"a": 2}},
            id="positional-only-and-same-keyword",
        ),
        pytest.param(
            positional,
            (),
            {"a": 2, "b": 3},
            {"a": 0, "kwargs": {"a": 2, "b": 3}},
            id="positional-only-omitted-and-same-keyword",
        ),
    ],
)
def test_bind_arguments(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    assert _bind_arguments(inspect.signature(func), args, kwargs) == expected


def test_bind_arguments_does_not_mutate_kwargs() -> None:
    kwargs = {"a": 2}
    _bind_arguments(inspect.signature(positional), (), kwargs)
    assert kwargs == {"a": 2}


def test_bind_arguments_required_positional_only_passed_as_keyword() -> None:
    def func(a: int, /, **kwargs: int) -> None:
        del a, kwargs

    with pytest.raises(TypeError, match=r"missing a required .*argument: 'a'"):
        _bind_arguments(inspect.signature(func), (), {"a": 1})


def test_bind_arguments_positional_only_without_var_keyword() -> None:
    def func(a: int = 0, /) -> None:
        del a

    with pytest.raises(TypeError, match=r"positional.only|unexpected keyword argument 'a'"):
        _bind_arguments(inspect.signature(func), (), {"a": 1})


###########################################
#     Tests for check_memoize_options     #
###########################################


@pytest.mark.parametrize(
    ("ignore", "key"),
    [
        pytest.param((), None, id="none"),
        pytest.param(["x"], None, id="ignore"),
        pytest.param((), str, id="key"),
    ],
)
def test_check_memoize_options_valid(ignore: list[str], key: Callable[..., str] | None) -> None:
    check_memoize_options(ignore=ignore, key=key)


@pytest.mark.parametrize("ignore", ["client", ""])
def test_check_memoize_options_ignore_str(ignore: str) -> None:
    with pytest.raises(
        TypeError, match=r"ignore must be a collection of parameter names, not a str"
    ):
        check_memoize_options(ignore=ignore, key=None)


def test_check_memoize_options_ignore_and_key() -> None:
    with pytest.raises(ValueError, match=r"ignore and key cannot be used together"):
        check_memoize_options(ignore=["x"], key=str)


##################################
#     Tests for memoize_with     #
##################################


def test_memoize_with_calls_get_cache_on_each_call(cache: Cache) -> None:
    calls = []

    def get_cache() -> Cache:
        calls.append(1)
        return cache

    func = memoize_with(get_cache)(add)
    func(1)
    func(1)
    assert len(calls) == 2


def test_memoize_with_does_not_call_get_cache_at_decoration() -> None:
    calls = []

    def get_cache() -> Cache:
        calls.append(1)
        return Cache()

    memoize_with(get_cache)(add)
    assert calls == []


def test_memoize_with_stores_under_call_key(cache: Cache) -> None:
    def double(x: int) -> int:
        return 2 * x

    memoize_with(lambda: cache)(double)(4)
    assert cache.get(build_key_function(double)((4,), {})) == 8


def test_memoize_with_sync_function_stays_sync(cache: Cache) -> None:
    assert not inspect.iscoroutinefunction(memoize_with(lambda: cache)(add))


def test_memoize_with_async_function_stays_async(cache: Cache) -> None:
    async def func() -> None:
        pass

    assert inspect.iscoroutinefunction(memoize_with(lambda: cache)(func))


def test_memoize_with_preserves_metadata(cache: Cache) -> None:
    assert inspect.unwrap(memoize_with(lambda: cache)(add)) is add


@pytest.mark.parametrize("ttl", [-1, float("nan")])
def test_memoize_with_invalid_ttl(ttl: float) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        memoize_with(Cache, ttl=ttl)


def test_memoize_with_ignore_str() -> None:
    with pytest.raises(TypeError, match=r"ignore must be a collection of parameter names"):
        memoize_with(Cache, ignore="x")


def test_memoize_with_ignore_and_key() -> None:
    with pytest.raises(ValueError, match=r"ignore and key cannot be used together"):
        memoize_with(Cache, ignore=["x"], key=str)


def test_memoize_with_unknown_ignore_name() -> None:
    decorator = memoize_with(Cache, ignore=["z"])
    with pytest.raises(ValueError, match=r"does not have: \['z'\]"):
        decorator(add)


def test_memoize_with_one_shot_ignore_applied_twice(cache: Cache) -> None:
    decorator = memoize_with(lambda: cache, ignore=iter(["y"]))
    decorator(add)
    second = decorator(add)
    second(1, object())
    assert cache.contains(build_key_function(add, ignore=["y"])((1,), {}))
