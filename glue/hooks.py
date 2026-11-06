"""Hermes hooks for fluent.

Every hook here must be fast and must never raise: a ``pre_tool_call`` callback that
raises or times out BLOCKS the tool call in Hermes. Each callback therefore wraps its
body and returns ``None`` (allow) on any internal error.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("hermes_plugins.fluent")


def install(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("transform_terminal_output", on_transform_terminal_output)


def on_pre_tool_call(tool_name: str = "", args: dict | None = None, **kwargs):
    """Check a terminal command before it runs. Returns None to allow."""
    try:
        if tool_name != "terminal":
            return None
        return None
    except Exception:  # never block the agent because of a fluent bug
        logger.debug("fluent: pre_tool_call failed", exc_info=True)
        return None


def on_post_tool_call(tool_name: str = "", args: dict | None = None, result: str = "", **kwargs):
    """Watch terminal results to learn (offer to adopt programs). Return value is ignored."""
    try:
        return None
    except Exception:
        logger.debug("fluent: post_tool_call failed", exc_info=True)
        return None


def on_transform_terminal_output(command: str = "", output: str = "", returncode=None, **kwargs):
    """Optionally append a one-line note to terminal output. None keeps it unchanged."""
    try:
        return None
    except Exception:
        logger.debug("fluent: transform_terminal_output failed", exc_info=True)
        return None
