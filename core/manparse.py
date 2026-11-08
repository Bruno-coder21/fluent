"""Read the options out of a man page (roff source).

Man pages come in many dialects (help2man, docbook/asciidoc like git, pod2man like
ffmpeg, hand-written). Rather than render roff, this reads only the "option header"
lines: the line after ``.TP``/``.PP``/``.LP``/``.sp``, the argument of ``.IP``, and
``.B``-style lines, keeping those that start with ``-`` once roff escapes are removed.
Prose that merely mentions an option is never read. Missing a few options only makes
the card more permissive, never stricter.

BSD and macOS man pages use the mdoc macros instead (``.It Fl a , Fl Fl auto-compress``);
their ``.It`` list items are read the same way, after turning the macros into text.
"""

from __future__ import annotations

import gzip
import re
import shlex
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

MAX_MAN_BYTES = 8_000_000

_HEADER_MACROS = (".TP", ".PP", ".LP", ".P", ".sp", ".HP")
_INLINE_MACROS = (".B ", ".BI ", ".BR ", ".IR ", ".I ", ".RB ")


def read_man_file(path: str | Path) -> str:
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rb") as fh:
            data = fh.read(MAX_MAN_BYTES)
    else:
        with open(p, "rb") as fh:
            data = fh.read(MAX_MAN_BYTES)
    return data.decode("utf-8", errors="replace")


def decode_roff(line: str) -> str:
    for pattern, repl in _ESCAPES:
        line = pattern.sub(repl, line)
    return line


# mdoc macros that only change how their words look; their names are dropped, their
# words kept. "Fl" (a dash before its argument) and "Ns" (no space) are handled apart.
_MDOC_MACROS = {
    "Ad", "Ar", "Aq", "Bq", "Brq", "Cm", "Dq", "Ec", "Ek", "Em", "Eo", "Ev", "Ic", "Li",
    "No", "Oc", "Oo", "Op", "Pa", "Pq", "Ql", "Qq", "Sq", "Sy", "Va", "Xc", "Xo",
}
_MDOC_PUNCT = {",", "|", ")", "]", ";", ":", "."}


def mdoc_text(args: str) -> str:
    """Text of an mdoc macro line's arguments: ``Fl a , Fl Fl all`` -> ``-a, --all``."""
    try:
        toks = shlex.split(args, posix=True)
    except ValueError:
        toks = args.split()
    out: list[str] = []
    dashes = 0
    glue = False

    def emit(word: str) -> None:
        nonlocal glue
        if word in _MDOC_PUNCT and out:
            out[-1] += word
        elif glue and out:
            out[-1] += word
        else:
            out.append(word)
        glue = False

    for tok in toks:
        if tok == "Fl":
            dashes += 1
            continue
        if tok == "Ns":
            glue = True
            continue
        if tok in _MDOC_MACROS:
            if dashes:
                emit("-" * dashes)
                dashes = 0
            continue
        if dashes:
            if tok in _MDOC_PUNCT:
                emit("-" * dashes)
            else:
                tok = "-" * dashes + tok
            dashes = 0
        emit(tok)
    if dashes:
        emit("-" * dashes)
    return " ".join(out)


def _mdoc_item(lines: list[str], i: int) -> str:
    """The macro text of the ``.It`` list item at ``lines[i]``, following ``Xo``/``Xc``."""
    rest = decode_roff(lines[i][3:]).strip()
    if not rest.startswith("Xo"):
        return rest
    parts = [rest[2:].strip()]
    for j in range(i + 1, min(i + 12, len(lines))):
        line = lines[j]
        if line.startswith(".Xc"):
            break
        parts.append(decode_roff(line[1:] if line.startswith(".") else line))
    return " ".join(p for p in parts if p).strip()


_MDOC_LONG_FORM = re.compile(r"long (?:option )?(?:form |name )?(?:is|are)\s+(--[A-Za-z][\w-]*)")


def mdoc_flags(src: str) -> list[Flag]:
    """Options of an mdoc (BSD/macOS) man page.

    Each option is a list item whose first macro is ``Fl``:
    ``.It Fl C Ar dir , Fl Fl cd Ar dir`` gives ``-C``/``--cd``, taking a value (``Ar``).
    Long forms named only in the text ("The long option form is .Fl Fl create .", or
    "The long form is .Fl Fl update .") are read too.
    """
    lines = src.splitlines()
    out: list[Flag] = []
    for i, raw in enumerate(lines):
        if not (raw.startswith(".It ") or raw == ".It"):
            continue
        item = _mdoc_item(lines, i)
        if not item.startswith("Fl"):
            continue
        names: list[str] = []
        for part in mdoc_text(item).split(","):
            word = part.strip().split(" ")[0].split("=")[0]
            if word.startswith("-") and word.strip("-") and word not in names:
                names.append(word)
        if names:
            takes_value = "Ar" in item.split()
            out.append(Flag(names=names, takes_value=takes_value))
    text = " ".join(mdoc_text(decode_roff(ln[1:])) if ln.startswith(".") else decode_roff(ln)
                    for ln in lines)
    for m in _MDOC_LONG_FORM.finditer(text):
        name = m.group(1).rstrip(".,;:")
        out.append(Flag(names=[name], takes_value=None, desc="long form"))
    return out


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


_SYNONYM = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)\s+is\s+(?:a synonym|an alias)\s+(?:of|for)\s+(--?[A-Za-z][\w-]*)")
# prose that states an option exists (curl): "This option was formerly known as
# --ftp-ssl" and "--eprt can be used to explicitly enable EPRT again"
_STATED = re.compile(r"formerly known as\s+(--[A-Za-z][\w-]*)"
                     r"|(?<![\w-])(--[A-Za-z][\w-]*)\s+can be used to explicitly enable")


def parse_man(src: str) -> list[Flag]:
    """Flags found in a man page, merged by name."""
    flags: dict[str, Flag] = {}
    for line in synopsis_lines(src):
        for flag in usage_flags(line):
            flags.setdefault(flag.names[0], flag)
    # prose like "--staged is a synonym of --cached" (git diff) names a real option
    text = decode_roff(src)
    for m in _SYNONYM.finditer(text):
        flags.setdefault(m.group(1), Flag(names=[m.group(1)], takes_value=None,
                                          desc=f"synonym of {m.group(2)}"))
    for m in _STATED.finditer(text):
        name = m.group(1) or m.group(2)
        flags.setdefault(name, Flag(names=[name], takes_value=None, desc="named in the manual"))
    for flag in mdoc_flags(src):
        key = flag.names[0]
        if key in flags:
            known = flags[key]
            known.names += [n for n in flag.names if n not in known.names]
            known.takes_value = known.takes_value or flag.takes_value
        else:
            flags[key] = flag
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
