"""Where cards live: one JSON file per program, plus a trash folder so every action can
be undone. Reads are cached by file modification time so the guard stays fast.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from .card import Card

MAX_ACTIONS = 30

DEFAULT_CONFIG = {
    "mode": "block",  # block | warn | off   (what to do with an option that doesn't exist)
    "risk_prompts": True,  # ask before destructive subcommands Hermes doesn't already ask about
    "not_now": [],  # programs the user doesn't want suggested
}


class CardStore:
    def __init__(self, base_dir: str | os.PathLike):
        self.base = Path(base_dir)
        self.cards_dir = self.base / "cards"
        self.trash_dir = self.base / "trash"
        self.actions_file = self.base / "actions.json"
        self.config_file = self.base / "config.json"
        self.counters_file = self.base / "counters.json"
        self._cache: dict[str, tuple[float, Card]] = {}
        self._lock = threading.Lock()
        self._programs_cache: tuple[float, list[str]] = (0.0, [])
        self._config_cache: tuple[float | None, dict] | None = None

    # ------------------------------------------------------------------ settings
    def config(self) -> dict:
        """Settings, re-read only when config.json changes (the guard asks on every command)."""
        try:
            mtime = self.config_file.stat().st_mtime
        except OSError:
            mtime = None
        if self._config_cache is not None and self._config_cache[0] == mtime:
            return dict(self._config_cache[1])
        data = _read_json(self.config_file, {})
        cfg = {**DEFAULT_CONFIG, **(data if isinstance(data, dict) else {})}
        self._config_cache = (mtime, cfg)
        return dict(cfg)

    def set_config(self, key: str, value) -> None:
        with self._lock:
            data = _read_json(self.config_file, {})
            data = data if isinstance(data, dict) else {}
            data[key] = value
            _atomic_write(self.config_file, json.dumps(data))
            self._config_cache = None

    # ------------------------------------------------------------------ counters (the rings)
    def counters(self) -> dict:
        data = _read_json(self.counters_file, {})
        return data if isinstance(data, dict) else {}

    def bump(self, **amounts: int) -> None:
        with self._lock:
            data = self.counters()
            for k, v in amounts.items():
                data[k] = int(data.get(k, 0)) + int(v)
            _atomic_write(self.counters_file, json.dumps(data))

    def programs_cached(self, ttl: float = 2.0) -> list[str]:
        """``programs()`` with a short cache: the guard asks on every terminal call."""
        now = time.monotonic()
        stamp, progs = self._programs_cache
        if now - stamp > ttl:
            progs = self.programs()
            self._programs_cache = (now, progs)
        return progs

    # ------------------------------------------------------------------ cards
    def card_path(self, program: str) -> Path:
        return self.cards_dir / f"{_safe(program)}.json"

    def programs(self) -> list[str]:
        if not self.cards_dir.is_dir():
            return []
        return sorted(p.stem for p in self.cards_dir.glob("*.json"))

    def load(self, program: str) -> Card | None:
        path = self.card_path(program)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._cache.pop(program, None)
            return None
        hit = self._cache.get(program)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            card = Card.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        self._cache[program] = (mtime, card)
        return card

    def save(self, card: Card) -> None:
        with self._lock:
            replaced = self._to_trash(card.program) if self.card_path(card.program).exists() else None
            _atomic_write(self.card_path(card.program), card.to_json())
            self._log({"op": "adopt", "program": card.program, "replaced": replaced})
            self._programs_cache = (0.0, [])

    def forget(self, program: str) -> bool:
        with self._lock:
            trashed = self._to_trash(program)
            if trashed is None:
                return False
            self._log({"op": "forget", "program": program, "trash": trashed})
            return True

    def undo(self) -> dict | None:
        """Undo the last adopt/forget. Returns the action undone, or None."""
        with self._lock:
            actions = self._actions()
            if not actions:
                return None
            last = actions.pop()
            program = last["program"]
            if last["op"] == "adopt":
                self._to_trash(program, log=False)
                if last.get("replaced"):
                    self._restore(program, last["replaced"])
            elif last["op"] == "forget":
                self._restore(program, last["trash"])
            self._write_actions(actions)
            return last

    # ------------------------------------------------------------------ internals
    def _to_trash(self, program: str, log: bool = True) -> str | None:
        src = self.card_path(program)
        if not src.exists():
            return None
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        dest = self.trash_dir / f"{_safe(program)}-{time.time_ns()}.json"
        os.replace(src, dest)
        self._cache.pop(program, None)
        self._programs_cache = (0.0, [])
        return dest.name

    def _restore(self, program: str, trash_name: str) -> None:
        src = self.trash_dir / trash_name
        if src.exists():
            self.cards_dir.mkdir(parents=True, exist_ok=True)
            os.replace(src, self.card_path(program))
            self._cache.pop(program, None)
            self._programs_cache = (0.0, [])

    def _actions(self) -> list[dict]:
        try:
            return json.loads(self.actions_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _write_actions(self, actions: list[dict]) -> None:
        _atomic_write(self.actions_file, json.dumps(actions[-MAX_ACTIONS:]))

    def _log(self, action: dict) -> None:
        action["time"] = time.time()
        actions = self._actions()
        actions.append(action)
        self._write_actions(actions)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _safe(program: str) -> str:
    return re.sub(r"[^\w.+-]", "_", program)[:100] or "_"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
