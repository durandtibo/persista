r"""Provide the decorator that caches the calls of a function, and the
keys of these calls."""

from __future__ import annotations

__all__ = ["build_key_function", "check_memoize_options", "memoize_with"]

import functools
import inspect
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from persista.cache.ttl import DEFAULT, validate_ttl
from persista.utils.canonical import hash_canonical

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from persista.cache.cache import Cache

P = ParamSpec("P")
R = TypeVar("R")


def build_key_function(
    func: Callable[..., Any],
    *,
    ignore: Collection[str] = (),
    key: Callable[..., str] | None = None,
) -> Callable[[tuple[Any, ...], dict[str, Any]], str]:
    r"""Build the function that computes the cache key of a call of a
    function.

    Without ``key``, the key of a call is the hash of the canonical
    encoding (see :func:`~persista.utils.canonical.encode_canonical`) of
    the module of the function, its qualified name, and its arguments
    bound to its parameters, with the default values. Two ways to write
    the same call, such as ``f(1)`` and ``f(a=1)``, therefore have the same
    key. For a bound method, the object it is bound to is the first
    argument.

    Args:
        func: The function whose calls need a key.
        ignore: The names of the parameters whose arguments are left out
            of the key. The name of a ``*args`` or ``**kwargs`` parameter
            leaves out all its arguments.
        key: A function that is called with the arguments of the call and
            returns its key. It replaces the key described above.

    Returns:
        A function that takes the positional arguments (a tuple) and the
        keyword arguments (a dict) of a call, and returns its key. It
        raises ``TypeError`` if the arguments do not match the signature
        of ``func``, or if an argument that is not ignored cannot be
        encoded, and ``ValueError`` if such an argument contains itself.
        With ``key``, it raises what ``key`` raises.

    Raises:
        TypeError: If ``ignore`` is a ``str``, or if ``key`` is not given and
            the calls of ``func`` cannot be identified: ``func`` has no
            ``__qualname__`` (such as a ``functools.partial``) or is a
            built-in method bound to an object.
        ValueError: If ``ignore`` and ``key`` are both given, if ``ignore``
            names a parameter that ``func`` does not have, or if ``key`` is
            not given and ``func`` has no signature.

    Example:
        ```pycon
        >>> from persista.cache.memoize import build_key_function
        >>> def add(x, y=0):
        ...     return x + y
        ...
        >>> make_key = build_key_function(add)
        >>> make_key((1,), {}) == make_key((), {"x": 1, "y": 0})
        True
        >>> make_key((1,), {}) == make_key((1.0,), {})
        False

        ```
    """
    check_memoize_options(ignore=ignore, key=key)
    if key is not None:
        return lambda args, kwargs: key(*args, **kwargs)

    # A decorator that uses functools.wraps keeps a reference to the
    # function it wraps, which tells whether it is a method.
    target = inspect.unwrap(func)
    bound: tuple[Any, ...] = ()
    if inspect.ismethod(target):
        # Two objects must not share the keys of their methods.
        bound = (target.__self__,)
        signature = inspect.signature(target.__func__)
    else:
        owner = getattr(target, "__self__", None)
        if owner is not None and not inspect.ismodule(owner):
            msg = (
                f"Cannot identify the calls of {func!r}, a built-in method bound to an "
                "object: pass key="
            )
            raise TypeError(msg)
        signature = inspect.signature(func)

    module = getattr(func, "__module__", None)
    qualname = getattr(func, "__qualname__", None)
    if qualname is None:
        msg = f"Cannot identify the calls of {func!r}, which has no __qualname__: pass key="
        raise TypeError(msg)
    ignored = frozenset(ignore)
    if unknown := sorted(ignored - signature.parameters.keys()):
        msg = f"ignore names parameters that {qualname} does not have: {unknown}"
        raise ValueError(msg)

    def make_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        arguments = {
            name: value
            for name, value in _bind_arguments(signature, (*bound, *args), kwargs).items()
            if name not in ignored
        }
        try:
            return hash_canonical((module, qualname, arguments))
        except TypeError as exc:
            msg = (
                f"Cannot compute the cache key of a call of {qualname}: {exc}. "
                "Leave the parameter out of the key with ignore=, or compute the key "
                "with key="
            )
            raise TypeError(msg) from exc

    return make_key


def _bind_arguments(
    signature: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    r"""Bind the arguments of a call to the parameters of a signature.

    Args:
        signature: The signature of the function.
        args: The positional arguments of the call.
        kwargs: The keyword arguments of the call. It is not modified.

    Returns:
        The value of every parameter, with the default values, keyed by
        the name of the parameter. The value of a ``*args`` parameter is
        a tuple and the value of a ``**kwargs`` parameter is a dict.

    Raises:
        TypeError: If the arguments do not match the signature.
    """
    # A keyword argument with the name of a positional-only parameter goes
    # to **kwargs. Signature.bind of Python 3.11 rejects it when the
    # parameter is left to its default, so it is bound separately.
    var_keyword = None
    same_names: dict[str, Any] = {}
    if kwargs:
        parameters = signature.parameters.values()
        var_keyword = next((p.name for p in parameters if p.kind is p.VAR_KEYWORD), None)
        if var_keyword is not None:
            same_names = {
                p.name: kwargs[p.name]
                for p in parameters
                if p.kind is p.POSITIONAL_ONLY and p.name in kwargs
            }
            kwargs = {name: value for name, value in kwargs.items() if name not in same_names}
    call = signature.bind(*args, **kwargs)
    call.apply_defaults()
    if var_keyword is not None and same_names:
        call.arguments[var_keyword] = {**call.arguments[var_keyword], **same_names}
    return call.arguments


def check_memoize_options(*, ignore: Collection[str], key: Callable[..., str] | None) -> None:
    r"""Check the options of a memoized function that do not depend on
    the function.

    Args:
        ignore: The names of the parameters to leave out of the key.
        key: The function that computes the key, if any.

    Raises:
        TypeError: If ``ignore`` is a ``str``.
        ValueError: If ``ignore`` and ``key`` are both given.

    Example:
        ```pycon
        >>> from persista.cache.memoize import check_memoize_options
        >>> check_memoize_options(ignore=("client",), key=None)
        >>> check_memoize_options(ignore="client", key=None)
        Traceback (most recent call last):
            ...
        TypeError: ignore must be a collection of parameter names, not a str: 'client'

        ```
    """
    if isinstance(ignore, str):
        msg = f"ignore must be a collection of parameter names, not a str: {ignore!r}"
        raise TypeError(msg)
    if ignore and key is not None:
        msg = "ignore and key cannot be used together"
        raise ValueError(msg)


def memoize_with(
    get_cache: Callable[[], Cache],
    *,
    ttl: float | None = DEFAULT,
    ignore: Collection[str] = (),
    key: Callable[..., str] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    r"""Build a decorator that caches the results of a function in the
    cache returned by ``get_cache`` at the time of each call.

    This is the implementation of
    :meth:`~persista.cache.cache.Cache.memoize` and of
    :func:`~persista.cache.interface.cached`.

    Args:
        get_cache: A function that returns the cache to use. It is called
            on every call of a decorated function.
        ttl: The time-to-live of the results. See
            :meth:`~persista.cache.cache.Cache.set`.
        ignore: The names of the parameters to leave out of the key. See
            :func:`build_key_function`.
        key: A function of the call that returns its key. See
            :func:`build_key_function`.

    Returns:
        A decorator for a sync or an ``async def`` function. The decorated
        function is of the same kind.

    Raises:
        TypeError: If ``ignore`` is a ``str``. The decorator raises
            ``TypeError`` as described in :func:`build_key_function`.
        ValueError: If ``ttl`` is negative or ``NaN``, or if ``ignore`` and
            ``key`` are both given. The decorator raises ``ValueError`` as
            described in :func:`build_key_function`.

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> from persista.cache.memoize import memoize_with
        >>> with Cache() as cache:
        ...     square = memoize_with(lambda: cache)(lambda x: x * x)
        ...     square(4)
        ...
        16

        ```
    """
    if ttl is not DEFAULT:
        validate_ttl(ttl)
    check_memoize_options(ignore=ignore, key=key)
    # Read once: the decorator can be applied to several functions.
    ignored = frozenset(ignore)

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        make_key = build_key_function(func, ignore=ignored, key=key)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                call_key = make_key(args, kwargs)
                return await get_cache().aget_or_compute(
                    call_key, functools.partial(func, *args, **kwargs), ttl=ttl
                )

            return cast("Callable[P, R]", async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            call_key = make_key(args, kwargs)
            return get_cache().get_or_compute(
                call_key, functools.partial(func, *args, **kwargs), ttl=ttl
            )

        return wrapper

    return decorator
