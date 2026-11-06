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


class CardStore:
    def __init__(self, base_dir: str | os.PathLike):
        self.base = Path(base_dir)
        self.cards_dir = self.base / "cards"
        self.trash_dir = self.base / "trash"
        self.actions_file = self.base / "actions.json"
        self._cache: dict[str, tuple[float, Card]] = {}
        self._lock = threading.Lock()

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
        return dest.name

    def _restore(self, program: str, trash_name: str) -> None:
        src = self.trash_dir / trash_name
        if src.exists():
            self.cards_dir.mkdir(parents=True, exist_ok=True)
            os.replace(src, self.card_path(program))
            self._cache.pop(program, None)

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
