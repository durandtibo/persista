r"""Check that the installed ``persista`` package works.

The script is run by the CI against a package that is *installed* (built
from the source distribution or the wheel, or downloaded from PyPI), not
against the source tree. It is a standalone script, not a pytest module:
it must run in an environment where only ``persista`` (and the requested
extras) are installed, so it does not import ``pytest`` or
``persista.testing``, and it does not import an optional library at module
level.

Usage::

    python tests/package/checks.py                  # no extra
    python tests/package/checks.py --extra duckdb   # duckdb is required
    python tests/package/checks.py --extra all      # every extra is required

A check on an optional library is skipped (and reported as skipped) when
the library is not installed, unless the extra that provides it was
requested with ``--extra``: then a missing library is a failure.

The script of the main branch also runs against the released packages, so
a check on a subpackage that the stable release does not have yet is
skipped.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import logging
import pkgutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import persista
from persista.cache import Cache
from persista.store import FileStore, InMemoryStore, SQLiteStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FunctionType

logger = logging.getLogger(__name__)

PACKAGE = "persista"

# Extra name -> module that the extra installs.
EXTRA_MODULES = {
    "duckdb": "duckdb",
    "faker": "faker",
    "httpx": "httpx",
    "lmdb": "lmdb",
    "psycopg": "psycopg",
    "redis": "redis",
    "requests": "requests",
    "rich": "rich",
    "urllib3": "urllib3",
}

# ``persista.testing`` imports ``pytest``, which no extra installs.
IMPORT_EXCLUDED = ("persista.testing",)

REQUIRED_EXTRAS: set[str] = set()


class SkipCheckError(Exception):
    r"""Raised by a check that cannot run in this environment."""


def is_installed(module: str) -> bool:
    r"""Indicate if a module can be imported, without importing it."""
    return importlib.util.find_spec(module) is not None


def require(extra: str) -> None:
    r"""Make sure a check can run with the library of an extra.

    Args:
        extra: The name of the extra.

    Raises:
        SkipCheckError: If the library is not installed and the extra
            was not requested.
        ModuleNotFoundError: If the library is not installed and the
            extra was requested.
    """
    module = EXTRA_MODULES[extra]
    if is_installed(module):
        return
    if extra in REQUIRED_EXTRAS:
        msg = f"the extra {extra!r} was requested but {module!r} is not installed"
        raise ModuleNotFoundError(msg)
    msg = f"{module!r} is not installed"
    raise SkipCheckError(msg)


def require_subpackage(name: str) -> None:
    r"""Make sure the installed version of ``persista`` has a subpackage.

    Args:
        name: The full name of the subpackage.

    Raises:
        SkipCheckError: If the installed version does not have it.
    """
    if not is_installed(name):
        msg = f"{name!r} is not in persista {persista.__version__}"
        raise SkipCheckError(msg)


#################################
#     Checks of the package     #
#################################


def is_editable_install() -> bool:
    r"""Indicate if ``persista`` is installed in editable mode (PEP
    610)."""
    text = importlib.metadata.distribution(PACKAGE).read_text("direct_url.json")
    return bool(text) and bool(json.loads(text or "{}").get("dir_info", {}).get("editable"))


def check_install_location() -> None:
    r"""Check that ``persista`` is imported from the installed package,
    not from the source tree.

    An editable install is imported from the source tree by design, so
    the check is skipped.
    """
    if is_editable_install():
        msg = "editable install"
        raise SkipCheckError(msg)

    location = Path(persista.__file__).resolve()
    source_tree = Path(__file__).resolve().parents[2] / "src"
    assert source_tree not in location.parents, (
        f"persista is imported from the source tree: {location}"
    )


def check_metadata() -> None:
    r"""Check the metadata of the installed distribution."""
    metadata = importlib.metadata.metadata(PACKAGE)
    assert metadata["Name"] == PACKAGE
    assert metadata["Requires-Python"], "Requires-Python is missing"
    assert metadata["License-Expression"] or metadata["License"], "the license is missing"
    installed = importlib.metadata.version(PACKAGE)
    assert installed != "0.0.0", "the version is the fallback of an uninstalled package"
    assert persista.__version__ == installed, f"{persista.__version__!r} != {installed!r}"


def check_distribution_files() -> None:
    r"""Check that the typing marker and the license are shipped."""
    assert (Path(persista.__file__).parent / "py.typed").is_file(), "py.typed is missing"
    files = {str(f) for f in importlib.metadata.files(PACKAGE) or []}
    assert any(f.endswith("LICENSE") for f in files), "LICENSE is missing"


def check_extras_installed() -> None:
    r"""Check that the distribution of each requested extra is
    installed."""
    missing = []
    for extra in sorted(REQUIRED_EXTRAS):
        try:
            importlib.metadata.version(extra)
        except importlib.metadata.PackageNotFoundError:
            missing.append(extra)
    assert not missing, f"the packages of the extras are not installed: {missing}"


def check_import_all_modules() -> None:
    r"""Check that every module of the package can be imported.

    This catches a module that is missing from the sdist or the wheel. A
    module may fail with ``ModuleNotFoundError`` if its optional library
    is not installed and its extra was not requested.
    """
    package = importlib.import_module(PACKAGE)
    required = {EXTRA_MODULES[e] for e in REQUIRED_EXTRAS}
    failures = []
    for info in pkgutil.walk_packages(package.__path__, prefix=f"{PACKAGE}."):
        if info.name.startswith(IMPORT_EXCLUDED):
            continue
        try:
            importlib.import_module(info.name)
        except ModuleNotFoundError as exc:
            missing = (exc.name or "").split(".")[0]
            if missing not in EXTRA_MODULES.values() or missing in required:
                failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001  an import can raise anything
            failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
    assert not failures, "failed to import:\n" + "\n".join(failures)


def check_imports() -> None:
    r"""Check that all main package objects can be imported
    correctly."""
    objects_to_import = [
        "persista.cache.Cache",
        "persista.store.BaseStore",
        "persista.store.InMemoryStore",
        "persista.store.store_from_uri",
    ]
    for a in objects_to_import:
        module_path, name = a.rsplit(".", maxsplit=1)
        module = importlib.import_module(module_path)
        assert getattr(module, name, None) is not None, f"Failed to import {a}"


################################
#     Checks of the features   #
################################


def check_imports_record() -> None:
    r"""Check that the objects of the record subpackage can be
    imported."""
    require_subpackage("persista.record")
    for module_path, name in (
        ("persista.record", "Record"),
        ("persista.record.store", "RecordStore"),
    ):
        module = importlib.import_module(module_path)
        assert getattr(module, name, None) is not None, f"Failed to import {name}"


def check_store_in_memory() -> None:
    r"""Check a round trip through the in-memory store."""
    with InMemoryStore() as store:
        store.set("1", {"name": "Ann"})
        assert store.get("1") == {"name": "Ann"}


def check_store_sqlite() -> None:
    r"""Check a round trip through the SQLite store."""
    with SQLiteStore(":memory:") as store:
        store.set("1", {"name": "Ann"})
        assert store.get("1") == {"name": "Ann"}


def check_store_file() -> None:
    r"""Check a round trip through the file store."""
    with tempfile.TemporaryDirectory() as path, FileStore(path) as store:
        store.set("1", {"name": "Ann"})
        assert store.get("1") == {"name": "Ann"}


def check_store_duckdb() -> None:
    r"""Check a round trip through the DuckDB store."""
    require("duckdb")
    duckdb_store = importlib.import_module("persista.store").DuckDBStore

    with duckdb_store(":memory:") as store:
        store.set("1", {"name": "Ann"})
        assert store.get("1") == {"name": "Ann"}


def check_store_lmdb() -> None:
    r"""Check a round trip through the LMDB store."""
    require("lmdb")
    lmdb_store = importlib.import_module("persista.store").LmdbStore

    with tempfile.TemporaryDirectory() as path, lmdb_store(path) as store:
        store.set("1", {"name": "Ann"})
        assert store.get("1") == {"name": "Ann"}


def check_cache() -> None:
    r"""Check that a value is stored in the cache."""
    with Cache() as cache:
        cache.set("greeting", "hello")
        assert cache.get("greeting") == "hello"


def check_record() -> None:
    r"""Check that the identifier of a record depends on its
    metadata."""
    require_subpackage("persista.record")
    record = importlib.import_module("persista.record").Record

    assert record.from_metadata({"a": 1, "b": 2}).id == record.from_metadata({"b": 2, "a": 1}).id


CHECKS: tuple[FunctionType, ...] = (
    check_install_location,
    check_metadata,
    check_distribution_files,
    check_extras_installed,
    check_import_all_modules,
    check_imports,
    check_imports_record,
    check_store_in_memory,
    check_store_sqlite,
    check_store_file,
    check_store_duckdb,
    check_store_lmdb,
    check_cache,
    check_record,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    r"""Parse the command line arguments.

    Args:
        argv: The arguments. ``None`` means ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="extra installed with the package: its library must be importable. "
        "Can be repeated or comma-separated; 'all' means every extra; '' means none.",
    )
    return parser.parse_args(argv)


def get_required_extras(values: Sequence[str]) -> set[str]:
    r"""Get the extras whose library is required.

    Args:
        values: The values of ``--extra``.

    Returns:
        The names of the extras.
    """
    extras = {e.strip() for value in values for e in value.split(",") if e.strip()}
    if "all" in extras:
        extras = (extras - {"all"}) | set(EXTRA_MODULES)
    # An extra without a known optional library has nothing to check.
    extras &= set(EXTRA_MODULES)
    return extras


def main(argv: Sequence[str] | None = None) -> int:
    r"""Run all the package checks.

    Args:
        argv: The command line arguments.

    Returns:
        The exit code: ``0`` if no check failed, ``1`` otherwise.
    """
    REQUIRED_EXTRAS.update(get_required_extras(parse_args(argv).extra))
    logger.info("Required extras: %s", sorted(REQUIRED_EXTRAS) or "none")
    failed, skipped = [], []
    for check in CHECKS:
        name = check.__name__
        try:
            check()
        except SkipCheckError as exc:
            skipped.append(name)
            logger.info("⏭️  %s skipped: %s", name, exc)
        except Exception:
            failed.append(name)
            logger.exception("❌ %s failed", name)
        else:
            logger.info("✅ %s passed", name)
    passed = len(CHECKS) - len(failed) - len(skipped)
    logger.info("%d passed, %d skipped, %d failed", passed, len(skipped), len(failed))
    if failed:
        logger.error("❌ Package check failed: %s", ", ".join(failed))
        return 1
    logger.info("✅ All package checks passed successfully!")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
