"""Adopt a program: read its help and man pages (for the installed version) into a Card.

Safety when running help (disclosed in the README):
* only ``<program> --help``-style calls, never a bare program or a real subcommand run;
* no shell, stdin closed, an empty scratch working directory, pagers disabled,
  C locale, a 5 s timeout per call and a 25 s budget for the whole adoption;
* subcommands are only explored for help styles that are known to handle ``--help``
  before doing anything (git parse-options, Go/cobra, argparse/click).
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .card import Card, Flag, Node
from .helpparse import ParsedHelp, parse_help, parse_list_lines
from .manparse import parse_man, read_man_file
from .risk import classify_card

CALL_TIMEOUT = 5.0
TOTAL_BUDGET = 25.0
MAX_CALLS = 400
MAX_OUTPUT = 4_000_000
WORKERS = 8

Progress = Callable[[str, dict], None]


class AdoptError(Exception):
    """A user-facing reason the program could not be adopted."""


@dataclass
class Strategy:
    root: list[list[str]] = field(default_factory=lambda: [["--help"], ["-h"], ["help"]])
    sub: list[str] = field(default_factory=lambda: ["{path}", "--help"])
    version: list[list[str]] = field(
        default_factory=lambda: [["--version"], ["-version"], ["version"], ["-V"]]
    )
    list_cmds: list[str] | None = None  # prints one subcommand per line (git)
    recurse: bool | None = None  # None: decide from the help style
    max_depth: int = 3
    require_man: bool = False  # help alone is known to be partial (git -h)
    abbrev_ok: bool | None = None
    single_dash_long: bool = False
    full_help: bool = False  # the root call already prints every option
    never_run: frozenset = frozenset()  # subcommands whose help is never executed


STRATEGIES: dict[str, Strategy] = {
    # git filter-branch prints a warning and sleeps 10 s before parsing its arguments,
    # and it rewrites history: never execute it, even with -h. Its man page is still read.
    "git": Strategy(root=[["--help"]], sub=["{path}", "-h"], version=[["--version"]],
                    list_cmds=["--list-cmds=main,nohelpers"], recurse=True, max_depth=1,
                    require_man=True, abbrev_ok=True,
                    never_run=frozenset({"filter-branch"})),
    "ffmpeg": Strategy(root=[["-hide_banner", "-h", "full"]], version=[["-hide_banner", "-version"]],
                       recurse=False, single_dash_long=True, full_help=True, abbrev_ok=False),
    "ffprobe": Strategy(root=[["-hide_banner", "-h", "full"]], version=[["-hide_banner", "-version"]],
                        recurse=False, single_dash_long=True, full_help=True, abbrev_ok=False),
    "ffplay": Strategy(root=[["-hide_banner", "-h", "full"]], version=[["-hide_banner", "-version"]],
                       recurse=False, single_dash_long=True, full_help=True, abbrev_ok=False),
    "curl": Strategy(root=[["--help", "all"], ["--help"]], recurse=False, full_help=True),
}

_SAFE_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME")


def resolve_program(program: str) -> str:
    """Absolute path of an installed program, or raise AdoptError."""
    if not program or "/" in program.strip("/") and not os.path.isabs(program):
        raise AdoptError(f"`{program}` is not a program name.")
    path = shutil.which(program)
    if not path:
        raise AdoptError(f"I can't find `{program}` on this machine.")
    return os.path.realpath(path)


class Adopter:
    def __init__(self, program: str, progress: Progress | None = None, *,
                 man_dirs: list[str] | None = None, budget: float = TOTAL_BUDGET):
        self.program = os.path.basename(program)
        self.progress = progress or (lambda stage, info: None)
        self.strategy = STRATEGIES.get(self.program, Strategy())
        self.man_dirs = man_dirs if man_dirs is not None else _man_dirs()
        self.budget = budget
        self.calls = 0
        self.timed_out = False
        self._lock = threading.Lock()
        self._start = 0.0
        self.path = ""
        self._scratch = ""

    # ------------------------------------------------------------------ public
    def run(self) -> Card:
        self.path = resolve_program(self.program)
        st = os.stat(self.path)
        self._start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="fluent-help-") as scratch:
            self._scratch = scratch
            version = self._version()
            card = Card(program=self.program, version=version, path=self.path,
                        size=st.st_size, mtime=st.st_mtime)
            self.progress("start", {"program": self.program, "version": version})
            root_text, parsed = self._root_help()
            card.style = parsed.style
            card.single_dash_long = self.strategy.single_dash_long or parsed.style == "ffmpeg"
            card.abbrev_ok = (self.strategy.abbrev_ok if self.strategy.abbrev_ok is not None
                              else parsed.style in ("gnu", "git"))
            root = self._node_from(card, [], parsed)
            card.nodes[""] = root
            self.progress("root", {"style": parsed.style, "options": len(root.flags)})
            if self._should_recurse(parsed):
                self._explore(card, root)
            self.progress("man", {})
            self._merge_man(card)
            for node in card.nodes.values():
                node.confidence = self._confidence(card, node, parsed if not node.path else None)
            classify_card(card)
            card.partial = self.timed_out
            self.progress("done", {"stats": card.stats()})
            return card

    # ------------------------------------------------------------------ steps
    def _version(self) -> str:
        for args in self.strategy.version:
            out = self._run(args, quiet=True)
            line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
            if line and "unknown" not in line.lower() and "illegal" not in line.lower():
                return _short_version(line)
        return ""

    def _root_help(self) -> tuple[str, ParsedHelp]:
        best: tuple[str, ParsedHelp] | None = None
        for args in self.strategy.root:
            text = self._run(args)
            parsed = parse_help(text, self.program)
            score = len(parsed.flags) + len(parsed.inherited) + len(parsed.subcommands)
            if best is None or score > (len(best[1].flags) + len(best[1].inherited) + len(best[1].subcommands)):
                best = (text, parsed)
            if score >= 3:
                break
        if best is None or not (best[1].flags or best[1].subcommands or best[1].inherited):
            raise AdoptError(f"`{self.program}` didn't print a help I can read, so I can't "
                             "check its commands. Nothing was saved.")
        return best

    def _should_recurse(self, parsed: ParsedHelp) -> bool:
        if self.strategy.recurse is not None:
            return self.strategy.recurse
        if parsed.style == "cobra":
            return True
        has_help_flag = any("--help" in f.names for f in parsed.flags)
        return bool(parsed.subcommands) and has_help_flag

    def _explore(self, card: Card, root: Node) -> None:
        if self.strategy.list_cmds:
            listed = parse_list_lines(self._run(self.strategy.list_cmds))
            if listed:
                root.subcommands = listed
        frontier = [[s] for s in root.subcommands]
        depth = 1
        while frontier and depth <= self.strategy.max_depth and not self._out_of_time():
            self.progress("subcommands", {"done": 0, "total": len(frontier), "depth": depth})
            next_frontier: list[list[str]] = []
            done = 0
            with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = {pool.submit(self._sub_help, path): path for path in frontier}
                for fut in cf.as_completed(futures):
                    path = futures[fut]
                    done += 1
                    try:
                        parsed = fut.result()
                    except Exception:
                        parsed = None
                    if parsed is not None:
                        node = self._node_from(card, path, parsed)
                        card.nodes[node.key] = node
                        next_frontier.extend(path + [s] for s in node.subcommands)
                    if done % 10 == 0 or done == len(frontier):
                        self.progress("subcommands", {"done": done, "total": len(frontier), "depth": depth})
            frontier = next_frontier
            depth += 1
        if frontier:
            self.timed_out = self.timed_out or self._out_of_time()

    def _sub_help(self, path: list[str]) -> ParsedHelp | None:
        if self._out_of_time():
            self.timed_out = True
            return None
        if path and path[0] in self.strategy.never_run:
            return ParsedHelp(style="man-only", usage=" ".join([self.program] + path))
        args: list[str] = []
        for part in self.strategy.sub:
            args.extend(path) if part == "{path}" else args.append(part)
        text = self._run(args)
        parsed = parse_help(text, self.program)
        if not (parsed.flags or parsed.subcommands or parsed.inherited or parsed.usage):
            return None
        return parsed

    def _node_from(self, card: Card, path: list[str], parsed: ParsedHelp) -> Node:
        node = Node(path=list(path), summary=parsed.summary, usage=parsed.usage,
                    flags=list(parsed.flags), subcommands=[n for n, _ in parsed.subcommands],
                    sources=["help"])
        with self._lock:
            _merge_flags(card.global_flags, parsed.inherited)
            for alias in parsed.aliases:
                if alias and alias != node.key:
                    card.alias_map.setdefault(alias, node.key)
        return node

    def _merge_man(self, card: Card) -> None:
        for node in list(card.nodes.values()):
            page = "-".join([self.program] + node.path)
            src_path = self._find_man(page)
            if not src_path:
                continue
            try:
                flags = parse_man(read_man_file(src_path))
            except Exception:
                continue
            if flags:
                _merge_flags(node.flags, flags)
                node.sources.append("man")

    def _confidence(self, card: Card, node: Node, root_parsed: ParsedHelp | None) -> str:
        has_man = "man" in node.sources
        if self.strategy.require_man and node.path:
            return "high" if has_man else "medium"
        if card.style == "ffmpeg":
            return "high" if self.strategy.full_help else "medium"
        if card.style == "cobra":
            return "high" if (node.usage or node.flags) else "medium"
        n_flags = len(node.flags)
        incomplete = root_parsed is not None and root_parsed.incomplete_hint and not self.strategy.full_help
        if incomplete and not has_man:
            return "medium"
        if n_flags >= 3 or has_man:
            return "high"
        return "medium" if n_flags else "low"

    # ------------------------------------------------------------------ helpers
    def _out_of_time(self) -> bool:
        return (time.monotonic() - self._start) > self.budget or self.calls >= MAX_CALLS

    def _run(self, args: list[str], quiet: bool = False) -> str:
        with self._lock:
            if self.calls >= MAX_CALLS:
                return ""
            self.calls += 1
        remaining = self.budget - (time.monotonic() - self._start) if self._start else CALL_TIMEOUT
        timeout = max(0.5, min(CALL_TIMEOUT, remaining))
        try:
            proc = subprocess.run(
                [self.path, *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self._scratch or None,
                env=_help_env(),
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if not quiet:
                self.timed_out = True
            return ""
        except OSError:
            return ""
        return proc.stdout[:MAX_OUTPUT].decode("utf-8", errors="replace")

    def _find_man(self, page: str) -> str | None:
        for d in self.man_dirs:
            for section in ("man1", "man8", "man6"):
                for ext in (".1.gz", ".1", ".8.gz", ".8", ".6.gz", ".6"):
                    p = os.path.join(d, section, page + ext)
                    if os.path.isfile(p):
                        return p
        return None


def adopt(program: str, progress: Progress | None = None, **kwargs) -> Card:
    return Adopter(program, progress, **kwargs).run()


# ----------------------------------------------------------------------------- utils


def _help_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env.update({
        "LANG": "C", "LC_ALL": "C", "NO_COLOR": "1", "TERM": "dumb",
        "PAGER": "cat", "GIT_PAGER": "cat", "MANPAGER": "cat",
        "GH_NO_UPDATE_NOTIFIER": "1", "GH_PROMPT_DISABLED": "1", "DOCKER_CLI_HINTS": "false",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env


def _man_dirs() -> list[str]:
    dirs = [d for d in os.environ.get("MANPATH", "").split(":") if d]
    dirs += ["/usr/local/share/man", "/usr/share/man", "/usr/local/man", "/opt/homebrew/share/man"]
    return [d for d in dict.fromkeys(dirs) if os.path.isdir(d)]


def _short_version(line: str) -> str:
    import re

    m = re.search(r"\d+(\.\d+)+([.-][\w]+)?", line)
    return m.group(0) if m else line[:40]


def _merge_flags(into: list[Flag], new: list[Flag]) -> None:
    """Union ``new`` into ``into`` by spelling. Never removes a known spelling."""
    index = {n: f for f in into for n in f.names}
    for flag in new:
        hit = next((index[n] for n in flag.names if n in index), None)
        if hit is None:
            copy = Flag(names=list(flag.names), takes_value=flag.takes_value, desc=flag.desc)
            into.append(copy)
            for n in copy.names:
                index[n] = copy
            continue
        for n in flag.names:
            if n not in hit.names:
                hit.names.append(n)
                index[n] = hit
        if flag.takes_value is True:
            hit.takes_value = True
        elif flag.takes_value is None and hit.takes_value is False:
            hit.takes_value = None  # one source says "optional value": be permissive
        if not hit.desc and flag.desc:
            hit.desc = flag.desc
