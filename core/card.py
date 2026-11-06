"""The "card": everything fluent learned about one installed program.

A card is plain JSON on disk. It records which version of which binary it describes
(path, size, modification time) so the guard can tell when the program changed and
the card is no longer trustworthy.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

CARD_FORMAT = 1

RISK_ORDER = {"read": 0, "unknown": 1, "change": 1, "destroy": 2}


@dataclass
class Flag:
    names: list[str]  # every spelling, e.g. ["-a", "--all"]
    takes_value: bool | None = False  # True required, None optional/unknown, False never
    desc: str = ""
    destroy: bool = False  # this flag makes the command destructive (rsync --delete)


@dataclass
class Node:
    """One command level: the program itself (path []) or a subcommand."""

    path: list[str] = field(default_factory=list)
    summary: str = ""
    usage: str = ""
    flags: list[Flag] = field(default_factory=list)
    subcommands: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)  # other names for this subcommand
    risk: str = "unknown"  # read | change | destroy | unknown
    network: bool = False
    confidence: str = "low"  # high | medium | low
    sources: list[str] = field(default_factory=list)  # "help", "man"

    @property
    def key(self) -> str:
        return " ".join(self.path)

    def flag_names(self) -> set[str]:
        return {n for f in self.flags for n in f.names}


@dataclass
class Card:
    program: str
    version: str = ""
    path: str = ""
    size: int = 0
    mtime: float = 0.0
    style: str = "generic"  # gnu | git | cobra | ffmpeg | generic
    abbrev_ok: bool = False  # unique prefixes of long options are accepted
    single_dash_long: bool = False  # options like -crf (ffmpeg style)
    nodes: dict[str, Node] = field(default_factory=dict)
    global_flags: list[Flag] = field(default_factory=list)
    alias_map: dict[str, str] = field(default_factory=dict)  # "container ls" -> "ps"
    partial: bool = False  # time budget ran out while reading
    created_at: float = field(default_factory=time.time)
    format: int = CARD_FORMAT

    # ------------------------------------------------------------------ queries
    @property
    def root(self) -> Node:
        return self.nodes.setdefault("", Node(path=[]))

    def node(self, path: list[str] | tuple[str, ...]) -> Node | None:
        return self.nodes.get(" ".join(path))

    def lookup(self, key: str) -> Node | None:
        """Find a node by its path key, following aliases ("container ls" -> "ps")."""
        node = self.nodes.get(key)
        if node is None and key in self.alias_map:
            node = self.nodes.get(self.alias_map[key])
        return node

    def stats(self) -> dict:
        risks = {"read": 0, "change": 0, "destroy": 0, "unknown": 0}
        flags = 0
        for n in self.nodes.values():
            flags += len(n.flags)
            if n.path:
                risks[n.risk if n.risk in risks else "unknown"] += 1
        return {
            "subcommands": sum(1 for n in self.nodes.values() if n.path),
            "options": flags + len(self.global_flags),
            **risks,
        }

    # ------------------------------------------------------------------ JSON
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Card":
        raw = json.loads(text)
        nodes = {}
        for key, n in raw.pop("nodes", {}).items():
            n["flags"] = [Flag(**f) for f in n.get("flags", [])]
            nodes[key] = Node(**n)
        globals_ = [Flag(**f) for f in raw.pop("global_flags", [])]
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(nodes=nodes, global_flags=globals_, **known)
