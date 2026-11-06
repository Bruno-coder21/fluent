"""Dashboard backend for fluent: one read-only endpoint, GET /api/plugins/fluent/summary.

Reads the same files the plugin writes under ``<HERMES_HOME>/plugin-data/fluent/``.
Card files are parsed once and cached by modification time; the work runs off the
event loop (``asyncio.to_thread``) as the dashboard docs ask.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_DEFAULTS = {"mode": "block", "risk_prompts": True}
_cache: dict[str, tuple[float, dict]] = {}


def _data_dir() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # public Hermes API

        return Path(plugin_data_dir("fluent"))
    except Exception:
        home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
        return Path(home) / "plugin-data" / "fluent"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _card_summary(path: Path) -> dict | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    card = _read(path, None)
    if not isinstance(card, dict):
        return None
    nodes = card.get("nodes") or {}
    risks = {"read": 0, "change": 0, "destroy": 0}
    options = len(card.get("global_flags") or [])
    subcommands = 0
    for node in nodes.values():
        options += len(node.get("flags") or [])
        if node.get("path"):
            subcommands += 1
            risk = node.get("risk")
            if risk in risks:
                risks[risk] += 1
    summary = {
        "program": card.get("program", path.stem),
        "version": card.get("version", ""),
        "subcommands": subcommands,
        "options": options,
        "learned_at": card.get("created_at", 0),
        "partial": bool(card.get("partial")),
        **risks,
    }
    _cache[str(path)] = (mtime, summary)
    return summary


def _summary() -> dict:
    base = _data_dir()
    cards = sorted((base / "cards").glob("*.json")) if (base / "cards").is_dir() else []
    programs = [s for s in (_card_summary(p) for p in cards) if s]
    counters = _read(base / "counters.json", {})
    raw = _read(base / "config.json", {})
    config = {**_DEFAULTS, **(raw if isinstance(raw, dict) else {})}
    counters = counters if isinstance(counters, dict) else {}
    return {
        "programs": programs,
        "counters": {
            "caught": int(counters.get("caught", 0)),
            "tokens_saved": int(counters.get("tokens_saved", 0)),
            "checked": int(counters.get("checked", 0)),
            "asked": int(counters.get("asked", 0)),
        },
        "config": {"mode": config.get("mode"), "risk_prompts": bool(config.get("risk_prompts"))},
    }


@router.get("/summary")
async def summary():
    return await asyncio.to_thread(_summary)
