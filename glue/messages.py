"""Everything fluent says to people. Short, plain words, one meaning per color:
🟢 read · 🟡 change · 🔴 destroy. Silence is the default; these only appear on request
or when they add something.
"""

from __future__ import annotations

import time

from ..core.card import Card, Node

DOT = {"read": "🟢", "change": "🟡", "destroy": "🔴", "unknown": "⚪"}
USAGE = ("/fluent adopt <program> · /fluent show <program> [subcommand] · "
         "/fluent forget <program> · /fluent undo")


def n(x: int) -> str:
    return f"{x:,}"


def plural(x: int, word: str) -> str:
    return f"{n(x)} {word}{'' if x == 1 else 's'}"


def learning(program: str, version: str = "", detail: str = "") -> str:
    head = f"📖 Learning {program} {version}".rstrip() + "…"
    return f"{head}\n{detail}" if detail else head


def adopt_progress(program: str, version: str, stage: str, info: dict) -> str | None:
    if stage == "start":
        return learning(program, version, "reading its help")
    if stage == "subcommands":
        total = info.get("total", 0)
        done = info.get("done", 0)
        return learning(program, version, f"reading {n(total)} commands · {n(done)}/{n(total)} {_bar(done, total)}")
    if stage == "man":
        return learning(program, version, "reading its manual pages")
    return None


def adopt_done(card: Card) -> str:
    s = card.stats()
    lines = [f"✅ {card.program} {card.version} is fluent".replace("  ", " ")]
    if s["subcommands"]:
        lines.append(f"{plural(s['subcommands'], 'command')} · {plural(s['options'], 'option')}")
        lines.append(f"{DOT['read']} {s['read']} read · {DOT['change']} {s['change']} change · "
                     f"{DOT['destroy']} {s['destroy']} destroy")
    else:
        lines.append(plural(s["options"], "option"))
    if card.partial:
        lines.append("Some commands took too long to read; those are never blocked.")
    lines.append("Undo: /fluent undo")
    return "\n".join(lines)


def show_card(card: Card) -> str:
    s = card.stats()
    lines = [f"{card.program} {card.version} · fluent ✅ · learned {_ago(card.created_at)}"]
    if s["subcommands"]:
        lines.append(f"{plural(s['subcommands'], 'command')} · {plural(s['options'], 'option')}")
        destroy = sorted(nd.key for nd in card.nodes.values() if nd.path and nd.risk == "destroy")
        if destroy:
            shown = ", ".join(destroy[:8]) + (f" +{len(destroy) - 8}" if len(destroy) > 8 else "")
            lines.append(f"{DOT['destroy']} asks before: {shown}")
        lines.append(f"Details: /fluent show {card.program} <command>")
    else:
        lines.append(f"{plural(s['options'], 'option')} · {_sources(card.root)}")
    return "\n".join(lines)


def show_node(card: Card, node: Node) -> str:
    name = f"{card.program} {node.key}".strip()
    risk = node.risk if node.risk in DOT else "unknown"
    words = {"read": "only reads", "change": "changes things", "destroy": "deletes things: asks first",
             "unknown": "not classified"}[risk]
    lines = [f"{DOT[risk]} {name} · {words}"]
    if node.summary:
        lines.append(node.summary)
    lines.append(f"{plural(len(node.flags), 'option')} · {_sources(node)} · {node.confidence} confidence")
    if node.subcommands:
        subs = ", ".join(node.subcommands[:12]) + (" …" if len(node.subcommands) > 12 else "")
        lines.append(f"Commands: {subs}")
    risky = [f.names[-1] for f in node.flags if f.destroy]
    if risky:
        lines.append(f"{DOT['destroy']} risky options: {', '.join(risky[:8])}")
    return "\n".join(lines)


def status(cards: list[Card]) -> str:
    if not cards:
        return ("fluent checks your agent's terminal commands against the real help of your "
                "programs.\nStart with: /fluent adopt git")
    names = " · ".join(f"{c.program} {c.version}".strip() for c in cards)
    return f"✅ Fluent in {len(cards)} program{'s' if len(cards) != 1 else ''}: {names}\n{USAGE}"


def _sources(node: Node) -> str:
    return " + ".join("man page" if s == "man" else "help" for s in node.sources) or "help"


def _bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return ""
    full = round(width * done / total)
    return "▰" * full + "▱" * (width - full)


def _ago(ts: float) -> str:
    secs = max(0, time.time() - ts)
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{round(secs / 60)} min ago"
    if secs < 129600:
        return f"{round(secs / 3600)} h ago"
    return f"{round(secs / 86400)} days ago"
