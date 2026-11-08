"""The guard: for one terminal command, decide allow / block / warn / ask.

Kept free of Hermes imports (the backend lookup is injected) so it can be tested with
real cards and fake environments.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field

from ..core.card import CARD_FORMAT, Card
from ..core.matcher import Check, Finding, check_invocation
from ..core.risk import core_already_asks
from ..core.shellsplit import might_invoke, split_command
from ..core.store import CardStore

TOKENS_PER_CATCH = 250  # ≈ a failed run's output + the retry it avoids (an estimate)


@dataclass
class Verdict:
    action: str = "allow"  # allow | block | warn | approve
    message: str = ""  # to the model (block/warn) or to the approval prompt (approve)
    notice: str = ""  # one line for the person, only when fluent did something
    rule_key: str = ""
    findings: list[Finding] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)  # adopted programs this command used


class Guard:
    def __init__(self, store: CardStore, *, which=shutil.which, backend=None):
        self.store = store
        self._which = which
        self._backend = backend or _default_backend
        self._fresh_cache: dict[str, tuple[float, bool]] = {}

    def check(self, command: str, env_type: str | None = None) -> Verdict:
        if not isinstance(command, str) or not command.strip():
            return Verdict()
        programs = self.store.programs_cached()
        if not programs or not might_invoke(command, programs):
            return Verdict()  # the hot path: no file is read for commands fluent doesn't know
        cfg = self.store.config()
        if cfg.get("mode") == "off":
            return Verdict()
        local = (env_type or self._backend()) == "local"
        findings: list[tuple[Finding, Card]] = []
        ask: tuple[Check, Card, str] | None = None
        used: list[str] = []
        for inv in split_command(command):
            if inv.program not in programs:
                continue
            card = self.store.load(inv.program)
            if card is None:
                continue
            if "/" in inv.program_path and (not os.path.isabs(inv.program_path)
                                            or os.path.realpath(inv.program_path) != card.path):
                continue  # ./git or /opt/other/git: not the binary this card was read from
            used.append(card.program)
            chk = check_invocation(inv, card)
            if not (local and self._fresh(card)):
                continue  # the card may not describe the program that will run: stay silent
            findings.extend((f, card) for f in chk.findings)
            if (ask is None and chk.destroy and cfg.get("risk_prompts", True)
                    and not core_already_asks(inv.segment)):
                ask = (chk, card, inv.segment)
        if findings and cfg.get("mode") == "warn" and ask is not None:
            # warn mode never drops a destructive-command prompt: ask, and mention the finding
            chk, card, segment = ask
            return Verdict("approve", message=_approval_message(chk, card, segment) + "\n"
                           + _model_message(findings, "warn"),
                           rule_key=_rule_key(chk, card), programs=used)
        if findings:
            mode = "warn" if cfg.get("mode") == "warn" else "block"
            return Verdict(mode, message=_model_message(findings, mode),
                           notice=_notice(findings), findings=[f for f, _ in findings],
                           programs=used)
        if ask is not None:
            chk, card, segment = ask
            return Verdict("approve", message=_approval_message(chk, card, segment),
                           rule_key=_rule_key(chk, card), programs=used)
        return Verdict(programs=used)

    def _fresh(self, card: Card, ttl: float = 10.0) -> bool:
        """Is the program that would run the same binary the card was read from?"""
        now = time.monotonic()
        hit = self._fresh_cache.get(card.program)
        if hit and now - hit[0] < ttl:
            return hit[1]
        ok = False
        try:
            path = self._which(card.program)
            if path:
                real = os.path.realpath(path)
                st = os.stat(real)
                ok = (card.format >= CARD_FORMAT and real == card.path and st.st_size == card.size
                      and abs(st.st_mtime - card.mtime) < 1e-3)
        except OSError:
            ok = False
        self._fresh_cache[card.program] = (now, ok)
        return ok


def _rule_key(chk: Check, card: Card) -> str:
    """One remembered "Always" covers one subcommand (and one risky option), no more."""
    key = ".".join(chk.node.path) if chk.node and chk.node.path else "-"
    return f"fluent:{card.program}:{key}" + (f":{chk.destroy_flag}" if chk.destroy_flag else "")


def terminal_backend() -> str:
    return _default_backend()


def _default_backend() -> str:
    # read the profile's own config (scope-aware), never a process-wide env var
    try:
        from hermes_cli.config import load_config_readonly  # public Hermes API

        term = (load_config_readonly() or {}).get("terminal") or {}
        return str(term.get("backend") or "local")
    except Exception:
        return "local"


def _model_message(findings: list[tuple[Finding, Card]], mode: str) -> str:
    lines = []
    for f, card in findings:
        where = f"`{f.command}` ({card.program} {card.version})".replace(" )", ")")
        if f.single_dash_hint:
            fix = f"{card.program} options use a single dash: use `{f.suggestion}`."
        elif f.suggestion:
            fix = f"Did you mean `{f.suggestion}`?"
        else:
            fix = f"See `{f.command} --help` for its options."
        lines.append(f"fluent: `{f.token}` is not an option of {where}, checked against the help "
                     f"of the version installed here. {fix}")
    tail = ("Fix the command and run it again." if mode == "block"
            else "The command ran anyway; if it failed, this is why.")
    return "\n".join(lines + [tail])


def _notice(findings: list[tuple[Finding, Card]]) -> str:
    f, card = findings[0]
    fix = f" → `{f.suggestion}`" if f.suggestion else ""
    more = f" (+{len(findings) - 1})" if len(findings) > 1 else ""
    return f"🛡️ fluent caught `{f.token}` in {f.command}{fix}{more}"


def _approval_message(chk: Check, card: Card, segment: str) -> str:
    name = " ".join([card.program] + (chk.node.path if chk.node else []))
    reason = chk.destroy_reason.rstrip(".")
    return f"🔴 fluent: `{name}` deletes things ({reason}).\nCommand: {segment}"
