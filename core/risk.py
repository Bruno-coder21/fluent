"""Risk classes for subcommands and flags: read / change / destroy (+ network).

Classification happens once, at adoption time, from the subcommand's name and the
first words of its own help summary. It is deliberately simple and explainable, and it
can only ADD caution: fluent never lowers or skips an approval Hermes asks for.
"""

from __future__ import annotations

import re

from .card import Card, Flag, Node

DESTROY_WORDS = frozenset(
    "delete remove rm rmi prune purge destroy drop wipe erase uninstall revoke truncate "
    "terminate clean kill del nuke".split()
)
READ_WORDS = frozenset(
    "list ls show view get status inspect log logs diff search info ps version help cat "
    "describe top stats history events port blame grep whoami check checks browse "
    "shortlog explain read print query count tree verify ls-files ls-remote ls-tree "
    "rev-parse show-ref show-branch cat-file whatchanged reflog".split()
)
NETWORK_WORDS = frozenset(
    "push pull fetch clone api upload download sync login logout publish deploy send "
    "request fork".split()
)
NETWORK_PROGRAMS = frozenset("gh curl wget ssh scp sftp ftp http httpie aws gcloud az".split())
READ_PROGRAMS = frozenset("jq yq grep rg ag cat head tail wc less more file stat".split())

_DESTROY_VERBS = ("delete", "remove", "prune", "purge", "destroy", "uninstall", "erase",
                  "wipe", "kill", "drop", "revoke")
_READ_VERBS = ("list", "show", "display", "view", "print", "inspect", "search", "describe",
               "check", "verify", "get", "output", "fetch information", "query")

# Only strong signals escalate a single option: "delete" alone is too common
# ("--delete-branch after merge") and would turn every merge into a prompt.
_DESTROY_FLAG = re.compile(
    r"\b(purge|wipe|erase|destroy|permanently|discard|throw away|extraneous|"
    r"without (asking|confirmation|prompting)|confirm deletion|"
    r"(skip|skips|bypass) (the )?(confirmation|prompt))\b",
    re.I,
)
_SAFE_FLAG = re.compile(r"\b(dry[- ]?run|do not|don't|never|prevent|instead of|keep)\b", re.I)

# What Hermes core ALREADY sends to its own approval prompt (tools/approval_detection.py).
# fluent skips these so the user is never asked twice for the same command.
CORE_ALREADY_ASKS = [
    re.compile(p)
    for p in (
        r"\bgit\s+reset\s+--h(a(r(d)?)?)?\b",
        r"\bgit\s+push\b.*--forc[a-z]*\b",
        r"\bgit\s+push\b.*\s-f\b",
        r"\bgit\s+clean\s+-[^\s]*f",
        r"\bgit\s+branch\s+-D\b",
        r"\bgit\s+branch\b.*(-d\b|--delete\b).*(-f\b|--force\b)",
        r"\bgit\s+branch\b.*(-f\b|--force\b).*(-d\b|--delete\b)",
        r"\bdocker(-compose|\s+compose)\s+.*\b(restart|stop|kill|down)\b",
        r"\bdocker\s+(\S+\s+)*?(restart|stop|kill)\b",
        r"\bdocker\s+.*(-H|--host)[=\s]+\S+",
        r"\bdocker\s+context\s+use\b",
        r"\bfind\b.*-delete\b",
        r"\brm\s+-[^\s]*r",
        r"\brm\s+--recursive\b",
    )
]


def core_already_asks(command_text: str) -> bool:
    return any(p.search(command_text) for p in CORE_ALREADY_ASKS)


# Known cases where the name says "delete" but the effect is recoverable or guarded:
# `git rm` refuses to remove files with local changes and git keeps the history.
RISK_OVERRIDES: dict[tuple[str, str], str] = {
    ("git", "rm"): "change",
    # `git clean` deletes nothing without -f (clean.requireForce), and Hermes core
    # already asks for `git clean -f...`: an extra prompt would only ever fire on dry runs.
    ("git", "clean"): "change",
}


def classify_node(program: str, node: Node) -> tuple[str, bool]:
    """Return (risk, network) for one node."""
    network = program in NETWORK_PROGRAMS
    override = RISK_OVERRIDES.get((program, node.key))
    if override:
        return override, network
    if not node.path:
        return ("read" if program in READ_PROGRAMS else "change"), network
    name = node.path[-1].lower()
    parts = set(re.split(r"[-_.]", name)) | {name}
    if any(p in NETWORK_WORDS for p in parts):
        network = True
    if parts & DESTROY_WORDS:
        return "destroy", network
    if name in READ_WORDS or parts & {"list", "ls", "show", "view", "status", "get", "info"}:
        return "read", network
    first = node.summary.strip().lower()
    if first.startswith(_DESTROY_VERBS):
        return "destroy", network
    if first.startswith(_READ_VERBS):
        return "read", network
    return "change", network


def is_destroy_flag(flag: Flag) -> bool:
    desc = flag.desc or ""
    if _SAFE_FLAG.search(desc):
        return False
    if _DESTROY_FLAG.search(desc):
        return True
    return any(n.lstrip("-") in ("purge", "remove-all") for n in flag.names)


def classify_card(card: Card) -> None:
    """Fill risk, network and destroy-flag marks on every node of a card, in place."""
    for node in card.nodes.values():
        node.risk, node.network = classify_node(card.program, node)
        for flag in node.flags:
            flag.destroy = is_destroy_flag(flag)
