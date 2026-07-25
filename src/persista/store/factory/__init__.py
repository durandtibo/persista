r"""Contain factories for stores."""

from __future__ import annotations

__all__ = ["BaseStoreFactory", "ConfigurableStoreFactory", "StoreFactory"]

from persista.store.factory.base import BaseStoreFactory
from persista.store.factory.configurable import ConfigurableStoreFactory
from persista.store.factory.vanilla import StoreFactory
