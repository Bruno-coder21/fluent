"""``@cli:<program> [command]``: put what fluent learned about a program into the
conversation (version, usage, commands, real options), so the agent gets it right the
first time instead of guessing."""

from __future__ import annotations

import asyncio
import logging

from .state import store

logger = logging.getLogger("hermes_plugins.fluent")

MAX_CHARS = 4000


def install(ctx) -> None:
    try:
        from agent.context_references import ContextCompletionItem, ContextReferenceProvider
    except Exception:  # older Hermes without plugin @-references: skip quietly
        return

    class CliReference(ContextReferenceProvider):
        prefix = "cli"
        description = "a program fluent learned: version, commands and real options"

        async def autocomplete(self, query: str, *, limit: int = 10):
            q = (query or "").strip().lower()
            items = []
            for p in store().programs():
                if p.startswith(q.split(" ")[0]):
                    items.append(ContextCompletionItem(text=p, meta="fluent card"))
            return items[:limit]

        async def expand(self, target: str):
            return await asyncio.to_thread(render_reference, target)

    try:
        ctx.register_context_reference(CliReference())
    except Exception:
        logger.debug("fluent: @cli: reference not registered", exc_info=True)


def render_reference(target: str) -> str | None:
    words = (target or "").replace(":", " ").split()
    if not words:
        return None
    card = store().load(words[0])
    if card is None:
        return f"fluent hasn't learned {words[0]} yet (/fluent adopt {words[0]})."
    node = card.lookup(" ".join(words[1:])) if len(words) > 1 else card.root
    if node is None:
        node = card.root
    name = " ".join([card.program] + node.path)
    lines = [f"fluent card: {name} — {card.program} {card.version}, read from its own help"
             f"{' and man page' if 'man' in node.sources else ''} on this machine."]
    if node.summary:
        lines.append(node.summary)
    if node.usage:
        lines.append(f"Usage: {node.usage}")
    if node.subcommands:
        lines.append(f"Commands ({len(node.subcommands)}): {', '.join(node.subcommands)}")
    destroy = sorted(n.key for n in card.nodes.values() if n.path and n.risk == "destroy"
                     and n.path[:len(node.path)] == node.path)
    if destroy:
        lines.append(f"Deletes things (fluent asks first): {', '.join(destroy)}")
    opts = []
    for f in node.flags + (card.global_flags if not node.path else []):
        spelled = ", ".join(f.names)
        if f.takes_value is True:
            spelled += " <value>"
        opts.append(spelled)
    if card.single_dash_long:
        lines.append("Options use a single dash (-crf, not --crf).")
    if opts:
        lines.append(f"Options ({len(opts)}): " + " · ".join(opts))
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" · ", 1)[0] + " · … (more: /fluent show " + name + ")"
    return text
