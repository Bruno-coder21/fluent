"""Read the options out of a man page (roff source).

Man pages come in many dialects (help2man, docbook/asciidoc like git, pod2man like
ffmpeg, hand-written). Rather than render roff, this reads only the "option header"
lines: the line after ``.TP``/``.PP``/``.LP``/``.sp``, the argument of ``.IP``, and
``.B``-style lines, keeping those that start with ``-`` once roff escapes are removed.
Prose that merely mentions an option is never read. Missing a few options only makes
the card more permissive, never stricter.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

from .card import Flag
from .helpparse import parse_option_spec, usage_flags

_ESCAPES = [
    (re.compile(r"\\f(\[[^\]]*\]|\(..|.)"), ""),  # font changes \fB \fR \f(CW \f[I]
    (re.compile(r"\\s[+-]?\d"), ""),  # size changes
    (re.compile(r"\\\(aq|\\\(cq|\\\(oq"), "'"),
    (re.compile(r"\\\(dq|\\\(lq|\\\(rq|\\\*\(lq|\\\*\(rq"), '"'),
    (re.compile(r"\\\((em|en|hy|mi)"), "-"),
    (re.compile(r"\\\(bu"), "•"),
    (re.compile(r"\\[&%c]"), ""),
    (re.compile(r"\\-"), "-"),
    (re.compile(r"\\e"), "\\\\"),
    (re.compile(r"\\ "), " "),
    (re.compile(r"\\\|"), ""),
]

_HEADER_MACROS = (".TP", ".PP", ".LP", ".P", ".sp", ".HP")
_INLINE_MACROS = (".B ", ".BI ", ".BR ", ".IR ", ".I ", ".RB ")


def read_man_file(path: str | Path) -> str:
    p = Path(path)
    data = p.read_bytes()
    if p.suffix == ".gz":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def decode_roff(line: str) -> str:
    for pattern, repl in _ESCAPES:
        line = pattern.sub(repl, line)
    return line


def option_headers(src: str) -> list[str]:
    """The decoded option-header lines of a man page."""
    lines = src.splitlines()
    out: list[str] = []
    for i, raw in enumerate(lines):
        cand = None
        if raw.startswith(_HEADER_MACROS) and (len(raw) == len(raw.split()[0])):
            j = i + 1
            while j < len(lines) and lines[j].startswith((".", "'")) and not lines[j].startswith(_INLINE_MACROS):
                if lines[j].startswith(".IP"):
                    break
                j += 1
            if j < len(lines):
                cand = lines[j]
                if cand.startswith(_INLINE_MACROS):
                    cand = cand.split(" ", 1)[1] if " " in cand else ""
        elif raw.startswith(".IP"):
            arg = raw[3:].strip()
            m = re.match(r'"((?:[^"\\]|\\.)*)"', arg)
            cand = m.group(1) if m else arg.split(" ")[0] if arg else None
        elif raw.startswith(_INLINE_MACROS):
            cand = raw.split(" ", 1)[1] if " " in raw else None
        if not cand:
            continue
        text = decode_roff(cand).replace('"', " ").strip()
        if text.startswith("-") and len(text) > 1 and text[1] != " ":
            out.append(text)
    return out


def synopsis_lines(src: str) -> list[str]:
    """Decoded text lines of the SYNOPSIS section."""
    out, inside = [], False
    for raw in src.splitlines():
        if raw.startswith(".SH"):
            inside = "SYNOPSIS" in raw.upper()
            continue
        if inside and raw and not raw.startswith((".", "'")):
            out.append(decode_roff(raw))
    return out


_SYNONYM = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*) is (?:a synonym|an alias) (?:of|for) (--?[A-Za-z][\w-]*)")


def parse_man(src: str) -> list[Flag]:
    """Flags found in a man page, merged by name."""
    flags: dict[str, Flag] = {}
    for line in synopsis_lines(src):
        for flag in usage_flags(line):
            flags.setdefault(flag.names[0], flag)
    # prose like "--staged is a synonym of --cached" (git diff) names a real option
    for m in _SYNONYM.finditer(decode_roff(src)):
        flags.setdefault(m.group(1), Flag(names=[m.group(1)], takes_value=None,
                                          desc=f"synonym of {m.group(2)}"))
    for header in option_headers(src):
        # a header can list several spellings: "--relative, -R" or "-a, --all"
        flag = parse_option_spec(header + "  ", style="man")
        if flag is None:
            continue
        key = flag.names[0]
        if key in flags:
            known = flags[key]
            for n in flag.names:
                if n not in known.names:
                    known.names.append(n)
            if flag.takes_value:
                known.takes_value = True
        else:
            flags[key] = flag
    return list(flags.values())
