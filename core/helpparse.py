"""Read a program's help text into options and subcommands.

Supported shapes (detected automatically):

* ``gnu``    GNU getopt_long, argparse, click, curl, jq, rsync: ``-a, --all   desc``
* ``git``    git parse-options (``git <sub> -h``): ``-q, --[no-]quiet   desc``
* ``cobra``  Go programs (gh, docker, kubectl): ``FLAGS`` / ``Options:`` sections and
             ``COMMANDS`` / ``Commands:`` sections, value types after the flag name
* ``ffmpeg`` single-dash long options (``-crf <int>``), read from ``-h full``

The parser never guesses: lines it can't read are skipped, which only makes the card
less complete. Completeness is tracked separately (confidence) so the guard never
blocks on an incomplete card.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .card import Flag

_NAME = re.compile(r"^(-{1,2})(\[no-\])?([A-Za-z0-9?@#][\w.+-]*)(\[?=.*|\[.*)?$")
_SPEC_TOKENS = re.compile(r"<[^>]*>|\{[^}]*\}|,|\||[^\s,|]+")
_ALLCAPS = re.compile(r"[A-Z][A-Z0-9_\-:.|/\[\]]*\.{0,3}")
_SUB_LINE = re.compile(r"^\s{1,12}([a-z][\w.-]*)(\*)?(:)?(?:\s{2,}|:\s+)(\S.*)?$")
_SUB_BARE = re.compile(r"^\s{1,12}([a-z][\w.-]*)(\*)?:?\s*$")
_HINT_INCOMPLETE = re.compile(
    r"-h full|--help all|-h long|for (more|all) options|see .?man |use .?--help-all", re.I
)


@dataclass
class ParsedHelp:
    style: str = "generic"
    flags: list[Flag] = field(default_factory=list)
    inherited: list[Flag] = field(default_factory=list)
    subcommands: list[tuple[str, str]] = field(default_factory=list)  # (name, summary)
    aliases: list[str] = field(default_factory=list)  # "container ls", "ps", ...
    summary: str = ""
    usage: str = ""
    incomplete_hint: bool = False


def detect_style(text: str, program: str = "") -> str:
    if program == "ffmpeg" or re.search(r"^usage: ffmpeg\b", text, re.M):
        return "ffmpeg"
    if re.search(r"^usage: git\b", text, re.M):
        return "git"
    if re.search(r"^USAGE\s*$", text, re.M) and re.search(r"^[A-Z ]*FLAGS\s*$", text, re.M):
        return "cobra"
    if re.search(r"^Usage:\s+\S+.*\[OPTIONS\]", text, re.M):
        return "cobra"
    if re.search(r"^(Available |Common |Management )?Commands:\s*$", text, re.M) and re.search(
        r"^(Flags|Options|Global Flags|Global Options):\s*$", text, re.M
    ):
        return "cobra"
    if re.search(r"^\s*-{1,2}[A-Za-z0-9].*", text, re.M):
        return "gnu"
    return "generic"


def parse_help(text: str, program: str = "", style: str | None = None) -> ParsedHelp:
    style = style or detect_style(text, program)
    if style == "ffmpeg":
        return _parse_ffmpeg(text)
    return _parse_sections(text, style)


def parse_option_spec(line: str, style: str = "gnu") -> Flag | None:
    """Parse one option line (``-a, --all  desc``) into a Flag, or None."""
    s = line.strip()
    if not re.match(r"-{1,2}(\[no-\])?[A-Za-z0-9?@#]", s):
        return None
    gap = re.search(r"\s{2,}|\t", s)
    spec, desc = (s[: gap.start()], s[gap.end():].strip()) if gap else (s, "")
    had_gap = gap is not None
    names: list[str] = []
    value: bool | None = False
    toks = _SPEC_TOKENS.findall(spec)
    value_tokens = 0
    for idx, tok in enumerate(toks):
        if tok in (",", "|"):
            continue
        m = _NAME.match(tok)
        if m and value_tokens == 0:
            dash, neg, name, rest = m.groups()
            names.append(dash + name)
            if neg:
                names.append(dash + "no-" + name)
            if rest:
                if rest.startswith("[=") or (rest.startswith("[") and value is not True):
                    value = None if value is False else value
                elif rest.startswith("="):
                    value = True
            continue
        if names and _is_value_token(tok, had_gap) and value_tokens < 3:
            value_tokens += 1
            if tok.startswith("[") and tok.endswith("]"):  # "[VALUE]" is optional
                value = None if value is False else value
            else:
                value = True
            continue
        rest_desc = " ".join(toks[idx:])
        desc = (rest_desc + " " + desc).strip() if desc else rest_desc
        break
    if not names:
        return None
    return Flag(names=_dedupe(names), takes_value=value, desc=desc[:200])


def parse_list_lines(text: str) -> list[str]:
    """One name per line (``git --list-cmds=main``)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r"[a-z][\w.-]*", line):
            out.append(line)
    return _dedupe(out)


# ----------------------------------------------------------------------------- internals


def _is_value_token(tok: str, had_gap: bool) -> bool:
    if tok[0] in "<[{":
        return True
    if _ALLCAPS.fullmatch(tok) and any(c.isalpha() for c in tok):
        return True
    # cobra types ("--limit int") and lowercase metavars ("--arg name value") only count
    # when the description is clearly separated by a gap, so prose is never mistaken.
    return had_gap and bool(re.fullmatch(r"[a-z][\w.:/-]*(\[\])?(\.\.\.)?", tok))


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _heading(line: str) -> str | None:
    """Return a normalized heading name, or None if ``line`` is not a heading."""
    s = line.strip()
    if not s or s.startswith("-") or len(s) > 60:
        return None
    indent = len(line) - len(line.lstrip())
    if indent > 2:
        return None
    if s.endswith(":") and not s.startswith(("usage:", "Usage:")):
        return s[:-1].strip().lower()
    if re.fullmatch(r"[A-Z][A-Z0-9 ]{2,}", s):
        return s.lower()
    return None


def _parse_sections(text: str, style: str) -> ParsedHelp:
    out = ParsedHelp(style=style, incomplete_hint=bool(_HINT_INCOMPLETE.search(text)))
    lines = text.splitlines()
    section = ""
    summary_done = style == "git"  # git -h has no description line
    for i, line in enumerate(lines):
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("usage:"):
            out.usage = out.usage or stripped[6:].strip()
            section = "usage"
            continue
        head = _heading(line)
        if head is not None:
            section = head
            continue
        if not stripped:
            continue
        if section == "usage" and not out.usage and stripped:
            out.usage = stripped
            continue
        if stripped.startswith("-"):
            summary_done = True  # the summary always comes before the first option
        indent = len(line) - len(line.lstrip())
        if not summary_done and section in ("", "usage") and indent <= 2 and not stripped.startswith("$"):
            if not low.startswith(("usage", "or:")):
                out.summary = stripped[:200]
                summary_done = True
            continue
        if _ignored(section):
            continue
        if "alias" in section and "command" not in section:
            for part in stripped.split(","):
                words = part.split()
                if len(words) >= 2:
                    out.aliases.append(" ".join(words[1:]))
            continue
        if "command" in section and not stripped.startswith("-"):
            m = _SUB_LINE.match(line) or _SUB_BARE.match(line)
            if m:
                out.subcommands.append((m.group(1), (m.group(4) if m.lastindex >= 4 else "") or ""))
            continue
        flag = parse_option_spec(line, style)
        if flag is None:
            continue
        if not flag.desc and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt and not nxt.startswith("-"):
                flag.desc = nxt[:200]
        if "inherited" in section or "global" in section:
            out.inherited.append(flag)
        else:
            out.flags.append(flag)
    out.subcommands = list(dict((n, s) for n, s in out.subcommands).items())
    return out


def _ignored(section: str) -> bool:
    return any(w in section for w in ("example", "learn more", "argument", "environment",
                                      "exit code", "see also", "json field"))


_FF_OPT = re.compile(r"^( {0,2})(-{1,2})([A-Za-z0-9_?][\w.]*)(.*)$")


def _parse_ffmpeg(text: str) -> ParsedHelp:
    out = ParsedHelp(style="ffmpeg", incomplete_hint=bool(_HINT_INCOMPLETE.search(text)))
    seen: dict[str, Flag] = {}
    main: set[str] = set()  # top-level ffmpeg options: their value shape is authoritative
    for line in text.splitlines():
        m = _FF_OPT.match(line)
        if not m:
            continue
        indent, dash, name, rest = m.groups()
        is_main = indent == ""
        if is_main:
            value = bool(re.match(r"\s([A-Za-z_][\w|:\[\]-]*)\s{2,}", rest))
            desc = rest.strip()
        else:  # AVOption line: "  -crf               <int>        E..V....... desc"
            value = "<" in rest.split("  ", 1)[0] or bool(re.match(r"\s+<", rest))
            desc = re.sub(r"^\s*<\w+>\s*[A-Z.]{6,}\s*", "", rest).strip()
        key = dash + name
        if key in seen:
            # an AVOption of some codec/filter must not change a main option's shape
            # (filters have an "y" option; the main -y takes no value)
            if is_main and key not in main:
                seen[key].takes_value, seen[key].desc = value, desc[:200]
                main.add(key)
            elif not is_main and key not in main:
                seen[key].takes_value = seen[key].takes_value or value
            continue
        if is_main:
            main.add(key)
        flag = Flag(names=[key], takes_value=value, desc=desc[:200])
        seen[key] = flag
        out.flags.append(flag)
    out.usage = "ffmpeg [options] [[infile options] -i infile]... {[outfile options] outfile}..."
    out.summary = "Hyper fast Audio and Video encoder"
    return out
