from __future__ import annotations

import importlib
import logging
import sys

import persista

logger = logging.getLogger(__name__)


def check_imports() -> None:
    r"""Check that all main package objects can be imported
    correctly."""
    logger.info("Checking imports...")
    objects_to_import = [
        "persista.store.BaseStore",
    ]
    for a in objects_to_import:
        module_path, name = a.rsplit(".", maxsplit=1)
        module = importlib.import_module(module_path)
        obj = getattr(module, name)
        assert obj is not None, f"Failed to import {a}"


def check_version() -> None:
    logger.info("Checking version...")
    assert isinstance(persista.__version__, str)


def main() -> None:
    r"""Run all package checks to validate installation and
    functionality."""
    try:
        check_imports()
        check_version()

        logger.info("✅ All package checks passed successfully!")
    except Exception:
        logger.exception("❌ Package check failed")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
