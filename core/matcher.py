"""Check one program invocation against that program's card.

The rules are strict about WHEN fluent may be sure:

* only LONG options are judged (``--name``; for ffmpeg-style programs ``-name``),
  never short options, positionals or subcommand names (aliases, plugins, extensions);
* only on a subcommand read with high confidence, before ``--``, and never on words
  that are known only at run time (``$VAR``, globs);
* unique-prefix abbreviations are accepted where the program accepts them (GNU, git).

Anything else is allowed silently. A finding only says "this option does not exist in
the help of the version installed here", with the closest real option when there is one.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .card import Card, Flag, Node
from .shellsplit import Invocation

_FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_PASSTHROUGH = re.compile(r"\b(COMMAND|CMD)\b[^\n]*\bARG|\[COMMAND\]|\[--\]\s*(COMMAND|ARG)", re.I)


@dataclass
class Finding:
    kind: str  # "unknown_option"
    program: str
    command: str  # "git log" / "ffmpeg"
    token: str  # the option as written, e.g. "--graphs"
    suggestion: str = ""  # closest real option, e.g. "--graph"
    single_dash_hint: bool = False  # "--crf" where "-crf" exists


@dataclass
class Check:
    """What fluent learned about one invocation."""

    program: str
    node: Node | None
    findings: list[Finding] = field(default_factory=list)
    destroy: bool = False  # the subcommand or a flag is destructive
    destroy_reason: str = ""
    certain: bool = False  # the subcommand was resolved with high confidence


def check_invocation(inv: Invocation, card: Card) -> Check:
    root = card.root
    args = inv.args
    globals_idx = _index(card.global_flags + root.flags)
    node = root
    path: list[str] = []
    pre_findings: list[Finding] = []
    i = 0
    # 1. walk subcommands; options met on the way belong to the command walked so far
    #    (git -C repo log, docker --context x ps) and are checked against it
    while i < len(args) and node.subcommands:
        w = args[i]
        t = w.text
        if w.dynamic or t == "--":
            break
        if t.startswith("-") and t != "-":
            here = _index(node.flags) | globals_idx
            if t.startswith("--") and not card.single_dash_long and node.confidence == "high":
                finding, _ = _check_long(t, here, sorted(n for n in here if n.startswith("--")),
                                         card, " ".join([card.program] + node.path))
                if finding:
                    pre_findings.append(finding)
            i += 1 + _value_skip(t, here, card)
            continue
        key = " ".join(path + [t])
        child = card.lookup(key)
        if child is None or (t not in node.subcommands and key not in card.alias_map):
            break
        node, path = child, child.path
        i += 1

    chk = Check(program=card.program, node=node, findings=pre_findings)
    if node.subcommands and i < len(args) and (args[i].dynamic or not args[i].text.startswith("-")):
        chk.findings = pre_findings if root.confidence == "high" else []
        return chk  # unknown subcommand (alias, plugin, extension): never judged
    chk.certain = node.confidence == "high"
    if node.risk == "destroy" and node.path:
        chk.destroy, chk.destroy_reason = True, node.summary or "deletes things"

    # 2. check the options of the resolved command
    known = _index(node.flags) | globals_idx
    long_names = sorted(n for n in known if n.startswith("--"))
    passthrough = bool(_PASSTHROUGH.search(node.usage or ""))
    command = " ".join([card.program] + node.path)
    expecting_value = False
    while i < len(args):
        w = args[i]
        t = w.text
        i += 1
        if expecting_value:
            expecting_value = False
            continue
        if t == "--" or (card.program == "find" and t in _FIND_EXEC):
            break  # after find -exec, the words belong to another program
        if w.dynamic and not t.startswith("--"):
            continue
        if not t.startswith("-") or t == "-":
            if passthrough:
                break
            continue
        if card.single_dash_long:
            finding, takes = _check_single_dash(t, known, card, command)
        elif t.startswith("--"):
            finding, takes = _check_long(t, known, long_names, card, command)
        else:
            finding, takes = None, _short_takes_value(t, known)
        if finding:
            chk.findings.append(finding)
        else:
            flag = _flag_for(t, known, long_names, card)
            if flag is not None and flag.destroy and not chk.destroy:
                chk.destroy, chk.destroy_reason = True, f"{flag.names[-1]}: {flag.desc}".strip(": ")
        expecting_value = takes
    if not chk.certain:
        chk.findings = []  # never judge options on a command we didn't fully read
    return chk


# ----------------------------------------------------------------------------- helpers


def _index(flags: list[Flag]) -> dict[str, Flag]:
    return {n: f for f in flags for n in f.names}


def _value_skip(token: str, known: dict[str, Flag], card: Card) -> int:
    """How many following words an option before the subcommand consumes (0 or 1)."""
    if "=" in token:
        return 0
    flag = known.get(token)
    if flag is None and token.startswith("--") and card.abbrev_ok:
        flag = _unique_prefix(token, known)
    return 1 if flag is not None and flag.takes_value is True else 0


def _check_long(token: str, known: dict[str, Flag], long_names: list[str], card: Card,
                command: str) -> tuple[Finding | None, bool]:
    name, eq, _ = token.partition("=")
    if _is_dynamic_name(name):
        return None, False
    flag = known.get(name)
    if flag is None and card.style == "git" and name.startswith("--no-"):
        # git parse-options accepts --no-<option> for any negatable long option
        positive = "--" + name[5:]
        flag = known.get(positive) or (_unique_prefix(positive, known) if card.abbrev_ok else None)
    if flag is None and card.abbrev_ok:
        flag = _unique_prefix(name, known)
        if flag is None and _ambiguous_prefix(name, long_names):
            return None, False  # the program will say "ambiguous"; not ours to judge
    if flag is not None:
        return None, bool(flag.takes_value is True and not eq)
    suggestion = _closest(name, long_names)
    return Finding("unknown_option", card.program, command, name, suggestion), False


def _check_single_dash(token: str, known: dict[str, Flag], card: Card,
                       command: str) -> tuple[Finding | None, bool]:
    """ffmpeg-style: every option is ``-name`` (with optional ``:stream`` specifier)."""
    if token.startswith("--"):
        name = token.split("=", 1)[0]
        if name in known:
            return None, bool(known[name].takes_value)
        single = "-" + name[2:].split(":", 1)[0]
        if _is_dynamic_name(name):
            return None, False
        if single in known:
            return Finding("unknown_option", card.program, command, name, single,
                           single_dash_hint=True), bool(known[single].takes_value)
        names = sorted(n for n in known if not n.startswith("--"))
        return Finding("unknown_option", card.program, command, name,
                       _closest(single, names)), False
    base = "-" + token[1:].split(":", 1)[0]
    if _is_dynamic_name(base) or len(base) < 2 or base[1:].lstrip("-").isdigit():
        return None, False
    flag = known.get(base)
    if flag is None and base.startswith("-no") and ("-" + base[3:]) in known:
        return None, False  # -nostats style negation of a boolean option
    if flag is None:
        names = sorted(n for n in known if not n.startswith("--"))
        return Finding("unknown_option", card.program, command, base, _closest(base, names)), False
    return None, bool(flag.takes_value is True)


def _short_takes_value(token: str, known: dict[str, Flag]) -> bool:
    """For ``-abc`` / ``-ovalue`` / ``-o value``: does the next word belong to this option?"""
    body = token[1:]
    for k, ch in enumerate(body):
        flag = known.get("-" + ch)
        if flag is None:
            return False  # unknown short option: never judged, don't guess its value
        if flag.takes_value is True:
            return k == len(body) - 1  # value is attached unless this is the last letter
    return False


def _flag_for(token: str, known: dict[str, Flag], long_names: list[str], card: Card) -> Flag | None:
    name = token.split("=", 1)[0]
    if card.single_dash_long:
        name = "-" + name.lstrip("-").split(":", 1)[0] if not name.startswith("--") else name
    flag = known.get(name)
    if flag is None and name.startswith("--") and card.abbrev_ok:
        flag = _unique_prefix(name, known)
    return flag


def _unique_prefix(name: str, known: dict[str, Flag]) -> Flag | None:
    hits = {n for n in known if n.startswith("--") and n.startswith(name)}
    if len(hits) == 1:
        return known[hits.pop()]
    flags = {id(known[h]): known[h] for h in hits}
    return next(iter(flags.values())) if len(flags) == 1 else None


def _ambiguous_prefix(name: str, long_names: list[str]) -> bool:
    return sum(1 for n in long_names if n.startswith(name)) > 1


def _is_dynamic_name(name: str) -> bool:
    return any(c in name for c in "$`*?[{")


def _closest(name: str, candidates: list[str]) -> str:
    hits = difflib.get_close_matches(name, candidates, n=1, cutoff=0.75)
    return hits[0] if hits else ""
