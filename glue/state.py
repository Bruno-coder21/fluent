"""Where fluent keeps its data: ``<HERMES_HOME>/plugin-data/fluent/`` (per profile)."""

from __future__ import annotations

import os
from pathlib import Path

from ..core.store import CardStore

_stores: dict[str, CardStore] = {}


def data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # public Hermes API
    except ImportError:  # outside Hermes (tests, scripts)
        home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        path = Path(home) / "plugin-data" / "fluent"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(plugin_data_dir("fluent"))


def store() -> CardStore:
    """The card store for the active profile (re-resolved on every call)."""
    key = str(data_dir())
    if key not in _stores:
        _stores[key] = CardStore(key)
    return _stores[key]
