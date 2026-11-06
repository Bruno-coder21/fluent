"""The /fluent slash command: adopt, show, forget, undo.

The handler is synchronous on purpose: Hermes runs sync command handlers on a worker
thread, where ``ctx.post_message`` / ``edit`` work, so the adoption can show a live
progress message that edits itself in place.
"""

from __future__ import annotations

import logging
import time

from ..core.adopt import AdoptError, adopt
from . import messages
from .state import store

logger = logging.getLogger("hermes_plugins.fluent")

DESCRIPTION = "Make your agent fluent in your programs: adopt, show, forget, undo"
ARGS_HINT = "adopt|show|forget|undo <program>"


def install(ctx) -> None:
    def handler(raw_args: str = "", **_kwargs):
        return handle(ctx, raw_args or "")

    ctx.register_command("fluent", handler, description=DESCRIPTION, args_hint=ARGS_HINT)


def handle(ctx, raw_args: str) -> str | None:
    parts = raw_args.split()
    if not parts:
        return messages.status(_cards())
    verb, rest = parts[0].lower(), parts[1:]
    try:
        if verb in ("adopt", "learn", "add"):
            return _adopt(ctx, rest)
        if verb in ("show", "card", "info"):
            return _show(rest)
        if verb in ("forget", "remove", "rm"):
            return _forget(rest)
        if verb == "undo":
            return _undo()
        if verb in ("help", "-h", "--help"):
            return messages.USAGE
    except Exception:  # a command must never crash the session
        logger.exception("fluent: /fluent %s failed", verb)
        return "Something went wrong inside fluent. Nothing was changed."
    return f"I don't know '{verb}'.\n{messages.USAGE}"


def _cards():
    s = store()
    return [c for c in (s.load(p) for p in s.programs()) if c is not None]


def _adopt(ctx, rest: list[str]) -> str | None:
    if not rest:
        return "Which program? /fluent adopt <program>"
    program = rest[0]
    live = LiveMessage(ctx)
    live.update(messages.learning(program), force=True)
    state = {"version": ""}

    def progress(stage: str, info: dict) -> None:
        if stage == "start":
            state["version"] = info.get("version", "")
        text = messages.adopt_progress(program, state["version"], stage, info)
        if text:
            live.update(text, force=stage in ("start", "man"))

    try:
        card = adopt(program, progress=progress)
    except AdoptError as e:
        return live.finish(f"⚠️ {e}")
    store().save(card)
    return live.finish(messages.adopt_done(card))


def _show(rest: list[str]) -> str:
    if not rest:
        return messages.status(_cards())
    card = store().load(rest[0])
    if card is None:
        return f"I haven't learned {rest[0]} yet. Try: /fluent adopt {rest[0]}"
    if len(rest) == 1:
        return messages.show_card(card)
    node = card.lookup(" ".join(rest[1:]))
    if node is None:
        return f"{card.program} {' '.join(rest[1:])} isn't in its help."
    return messages.show_node(card, node)


def _forget(rest: list[str]) -> str:
    if not rest:
        return "Which program? /fluent forget <program>"
    if store().forget(rest[0]):
        return f"Forgot {rest[0]}. Undo: /fluent undo"
    return f"I wasn't fluent in {rest[0]}."


def _undo() -> str:
    action = store().undo()
    if action is None:
        return "Nothing to undo."
    if action["op"] == "adopt":
        return f"↩️ Undone: {action['program']} is no longer adopted."
    return f"↩️ Undone: {action['program']} is back."


class LiveMessage:
    """One message that edits itself in place; falls back to a normal reply."""

    def __init__(self, ctx, min_interval: float = 0.7):
        self.ctx = ctx
        self.handle = None  # None: not posted yet; False: live messages unavailable
        self.min_interval = min_interval
        self._last = 0.0

    def update(self, text: str, force: bool = False) -> None:
        now = time.monotonic()
        if self.handle is False or (not force and now - self._last < self.min_interval):
            return
        self._last = now
        try:
            if self.handle is None:
                h = self.ctx.post_message(text)
                self.handle = h if getattr(h, "ok", False) else False
            else:
                self.handle.edit(text)
        except Exception:
            self.handle = False

    def finish(self, text: str) -> str | None:
        """Show the final text. Returns it as the reply only if it couldn't be shown live."""
        if self.handle:
            try:
                result = self.handle.edit(text)
                if not isinstance(result, dict) or result.get("ok", True):
                    return None
            except Exception:
                pass
        return text
