"""Hermes hooks for fluent.

Every hook here must be fast and must never raise: a ``pre_tool_call`` callback that
raises or times out BLOCKS the tool call in Hermes. Each callback therefore wraps its
body and returns ``None`` (allow) on any internal error.
"""

from __future__ import annotations

import contextvars
import json
import logging
import shutil
import threading
from collections import OrderedDict

from ..core.learn import NEVER_SUGGEST, looks_like_option_error
from ..core.shellsplit import is_shell_builtin, split_command
from .guard import TOKENS_PER_CATCH, Guard
from .state import store

logger = logging.getLogger("hermes_plugins.fluent")

_ctx = None
_guards: dict[int, Guard] = {}
_warn_notes: "OrderedDict[str, str]" = OrderedDict()  # tool_call_id -> note (warn mode)
_offered: set[tuple[str, str]] = set()  # (session_id, program) already suggested
_lock = threading.Lock()


def install(ctx) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("transform_terminal_output", on_transform_terminal_output)


def guard() -> Guard:
    s = store()
    g = _guards.get(id(s))
    if g is None or g.store is not s:
        g = _guards[id(s)] = Guard(s)
    return g


def on_pre_tool_call(tool_name: str = "", args: dict | None = None, tool_call_id: str = "",
                     **kwargs):
    """Check a terminal command before it runs. Returns None to allow."""
    try:
        if tool_name != "terminal" or not isinstance(args, dict):
            return None
        verdict = guard().check(args.get("command") or "")
        if verdict.action == "block":
            store().bump(caught=len(verdict.findings),
                         tokens_saved=TOKENS_PER_CATCH * len(verdict.findings))
            notify(verdict.notice)
            return {"action": "block", "message": verdict.message}
        if verdict.action == "warn":
            store().bump(caught=len(verdict.findings))
            _remember_note(tool_call_id, verdict.message)
            notify(verdict.notice)
            return None
        if verdict.action == "approve":
            store().bump(asked=1)
            return {"action": "approve", "message": verdict.message, "rule_key": verdict.rule_key}
        return None
    except Exception:  # never block the agent because of a fluent bug
        logger.debug("fluent: pre_tool_call failed", exc_info=True)
        return None


def on_post_tool_call(tool_name: str = "", args: dict | None = None, result: str = "",
                      session_id: str = "", **kwargs):
    """Learn: when a program rejects an option, offer to adopt it (never adopt silently)."""
    try:
        if tool_name != "terminal" or not isinstance(args, dict):
            return None
        data = json.loads(result) if isinstance(result, str) and result.startswith("{") else {}
        if not isinstance(data, dict) or data.get("exit_code") in (0, None):
            return None
        if not looks_like_option_error(str(data.get("output") or "")):
            return None
        s = store()
        adopted = set(s.programs_cached())
        not_now = set(s.config().get("not_now") or [])
        for inv in split_command(args.get("command") or ""):
            p = inv.program
            if p in adopted or p in not_now or p in NEVER_SUGGEST or is_shell_builtin(p):
                continue
            with _lock:
                if (session_id, p) in _offered:
                    continue
                _offered.add((session_id, p))
            if not shutil.which(p):
                continue
            notify(f"💡 {p} rejected an option. I can learn {p} from its own help in a few "
                   f"seconds: /fluent adopt {p} · not now: /fluent not-now {p}")
            break
        return None
    except Exception:
        logger.debug("fluent: post_tool_call failed", exc_info=True)
        return None


def on_transform_terminal_output(command: str = "", output: str = "", returncode=None,
                                 tool_call_id: str = "", **kwargs):
    """In warn mode, add the one-line explanation under the output of the failed command."""
    try:
        with _lock:
            note = _warn_notes.pop(tool_call_id, None) if tool_call_id else None
        if note:
            return f"{output}\n\n{note}"
        return None
    except Exception:
        logger.debug("fluent: transform_terminal_output failed", exc_info=True)
        return None


def notify(text: str) -> None:
    """Post one line to the conversation, without making the hook wait for it."""
    if not text or _ctx is None:
        return
    context = contextvars.copy_context()

    def run():
        try:
            context.run(_ctx.post_message, text)
        except Exception:
            logger.debug("fluent: notice failed", exc_info=True)

    threading.Thread(target=run, name="fluent-notice", daemon=True).start()


def _remember_note(tool_call_id: str, note: str) -> None:
    if not tool_call_id:
        return
    with _lock:
        _warn_notes[tool_call_id] = note
        while len(_warn_notes) > 200:
            _warn_notes.popitem(last=False)
