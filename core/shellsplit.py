"""Split a shell command line into the programs it runs.

Standard library only, no Hermes imports. The splitter is conservative on purpose:
whenever a construct is too dynamic to read reliably (variables, command substitution,
globs), the affected words are marked ``dynamic``, and when the whole command is unsafe
to read (heredocs, unbalanced quotes, huge input) nothing is returned. The guard only
ever acts on what it could read with certainty.

    >>> [i.program for i in split_command("sudo -u bob git -C repo log --oneline | head -5")]
    ['git', 'head']
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

MAX_COMMAND_CHARS = 8000
MAX_NESTING = 2


@dataclass(frozen=True)
class Word:
    """One shell word after quote removal.

    ``dynamic`` is True when part of the word is only known at run time: an unquoted
    or double-quoted ``$VAR``/``$(...)``/backtick, or an unquoted glob character.
    The raw expansion text is kept inside ``text`` (for example ``--preset=$P``).
    """

    text: str
    dynamic: bool = False


@dataclass(frozen=True)
class Invocation:
    """One program the command line runs, with its arguments."""

    program: str  # basename, e.g. "git"
    args: tuple[Word, ...]
    program_path: str  # as written, e.g. "/usr/bin/git"
    segment: str  # readable text of this simple command

    @property
    def argv(self) -> tuple[str, ...]:
        return tuple(w.text for w in self.args)


@dataclass(frozen=True)
class _Op:
    op: str


# Shell builtins and keywords: never "programs" worth adopting.
BUILTINS = frozenset(
    """
    . : [ [[ ]] alias bg bind break builtin case cd command compgen complete continue
    declare dirs disown do done echo elif else enable esac eval exec exit export false fc
    fg fi for function getopts hash help history if in jobs kill let local logout mapfile
    popd printf pushd pwd read readarray readonly return select set shift shopt source
    suspend test then time times trap true type typeset ulimit umask unalias unset until
    wait while { } !
    """.split()
)

# Reserved words that may precede a command in the same segment.
_PEEL_KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{",
                            "}", "fi", "done", "esac"})
# Reserved words whose segment holds no command we can read reliably.
_SKIP_KEYWORDS = frozenset({"for", "case", "select", "function", "[[", "coproc"})

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_REDIR = re.compile(r"<<<|<<-|<<|<>|<&|>&|>>|>\||<|>")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})


@dataclass(frozen=True)
class _Wrapper:
    value_opts: frozenset = frozenset()  # options that take the next word as a value
    stop_opts: frozenset = frozenset()  # options meaning "no command is executed"
    positionals: int = 0  # positional words before the command (timeout DURATION)


def _w(values: str = "", stops: str = "", positionals: int = 0) -> _Wrapper:
    return _Wrapper(frozenset(values.split()), frozenset(stops.split()), positionals)


_WRAPPERS: dict[str, _Wrapper] = {
    "sudo": _w("-u -g -C -D -h -p -r -t -U -T --user --group --close-from --chdir --host "
               "--prompt --role --type --other-user --command-timeout",
               "-e --edit -l --list -V --version -v --validate"),
    "doas": _w("-u -C"),
    "env": _w("-u --unset -C --chdir", "-S --split-string"),
    "time": _w("-f --format -o --output"),
    "nice": _w("-n --adjustment"),
    "ionice": _w("-c --class -n --classdata -p --pid -P --pgid -u --uid"),
    "nohup": _w(),
    "stdbuf": _w("-i -o -e --input --output --error"),
    "timeout": _w("-s --signal -k --kill-after", positionals=1),
    "command": _w("", "-v -V"),
    "exec": _w("-a"),
    "builtin": _w("", ""),
    "xargs": _w("-a --arg-file -d --delimiter -E -I -L -n --max-args -P --max-procs -s "
                "--max-chars --process-slot-var"),
    "watch": _w("-n --interval -q --equexit"),
}


def split_command(command: str) -> list[Invocation]:
    """Return the programs a shell command line runs, in order. Never raises."""
    try:
        return _split(command, 0)
    except Exception:
        return []


def might_invoke(command: str, programs) -> bool:
    """Cheap prefilter: could this command mention any of ``programs``?"""
    return any(p and p in command for p in programs)


def is_shell_builtin(name: str) -> bool:
    return name in BUILTINS


# --------------------------------------------------------------------------- internals


def _split(command: str, depth: int) -> list[Invocation]:
    if not command or len(command) > MAX_COMMAND_CHARS or depth > MAX_NESTING:
        return []
    tokens = _tokenize(command)
    if tokens is None:
        return []
    out: list[Invocation] = []
    segment: list[Word] = []
    for tok in tokens + [_Op(";")]:
        if isinstance(tok, _Op):
            if segment:
                out.extend(_resolve(segment, depth))
            segment = []
        else:
            segment.append(tok)
    return out


def _resolve(words: list[Word], depth: int) -> list[Invocation]:
    """Turn one simple command (a list of words) into invocations."""
    segment_text = " ".join(w.text for w in words)
    i, n = 0, len(words)
    for _ in range(12):  # peel keywords, assignments and wrappers
        while i < n and not words[i].dynamic and (
            words[i].text in _PEEL_KEYWORDS or _ASSIGNMENT.match(words[i].text)
        ):
            i += 1
        if i >= n:
            return []
        first = words[i]
        if first.dynamic:
            return []
        if first.text in _SKIP_KEYWORDS:
            return []
        name = _basename(first.text)
        if name == "watch":
            return _resolve_watch(words, i + 1, depth)
        spec = _WRAPPERS.get(name)
        if spec is None:
            break
        if name == "builtin":
            return []
        i = _skip_wrapper_options(words, i + 1, spec)
        if i < 0:
            return []
        if name == "env":
            while i < n and _ASSIGNMENT.match(words[i].text):
                i += 1
    if i >= n:
        return []
    first = words[i]
    if first.dynamic:
        return []
    name = _basename(first.text)
    if not name:
        return []
    args = tuple(words[i + 1:])
    if name in _SHELLS:
        inner = _shell_c_string(args)
        if inner is not None:
            return _split(inner, depth + 1) if not inner_is_dynamic(args) else []
    return [Invocation(name, args, first.text, segment_text)]


def inner_is_dynamic(args: tuple[Word, ...]) -> bool:
    """True when the ``-c`` string of a shell call contains run-time expansions."""
    for k, w in enumerate(args):
        if _is_short_cluster_with(w.text, "c") and k + 1 < len(args):
            return args[k + 1].dynamic
    return False


def _shell_c_string(args: tuple[Word, ...]) -> str | None:
    """For ``bash -c 'cmd'`` / ``bash -lc 'cmd'``, return ``'cmd'``."""
    k = 0
    while k < len(args):
        t = args[k].text
        if t == "--" or not t.startswith("-") or t == "-":
            return None
        if t in ("-o", "+o", "-O", "+O"):
            k += 2
            continue
        if _is_short_cluster_with(t, "c"):
            return args[k + 1].text if k + 1 < len(args) else None
        k += 1
    return None


def _is_short_cluster_with(token: str, letter: str) -> bool:
    return (len(token) >= 2 and token[0] == "-" and token[1] != "-"
            and token[1:].isalpha() and letter in token[1:])


def _skip_wrapper_options(words: list[Word], i: int, spec: _Wrapper) -> int:
    """Skip a wrapper's own options. Returns the index of the wrapped command, or -1."""
    n = len(words)
    while i < n:
        t = words[i].text
        if t == "--":
            i += 1
            break
        if not t.startswith("-") or t == "-":
            break
        if t in spec.stop_opts:
            return -1
        if t in spec.value_opts:
            i += 2
            continue
        if t.startswith("--") and "=" in t:
            i += 1
            continue
        i += 1
    i += spec.positionals
    return i if i < n else -1


def _resolve_watch(words: list[Word], i: int, depth: int) -> list[Invocation]:
    """``watch [opts] cmd...`` runs ``sh -c "cmd..."`` unless ``-x`` is given."""
    spec = _WRAPPERS["watch"]
    exec_mode = any(w.text in ("-x", "--exec") for w in words[i:])
    i = _skip_wrapper_options(words, i, spec)
    if i < 0:
        return []
    rest = words[i:]
    if exec_mode or len(rest) > 1:
        return _resolve(list(rest), depth)
    if rest[0].dynamic:
        return []
    return _split(rest[0].text, depth + 1)


def _basename(path: str) -> str:
    return os.path.basename(path.lstrip("\\"))


# --------------------------------------------------------------------------- tokenizer


def _tokenize(s: str):
    """Split ``s`` into Words and _Ops. Returns None when ``s`` can't be read safely."""
    toks: list = []
    buf: list[str] = []
    dyn = False
    in_word = False
    drop_next_word = False  # the next word is a redirection target
    i, n = 0, len(s)

    def flush():
        nonlocal buf, dyn, in_word, drop_next_word
        if in_word:
            if drop_next_word:
                drop_next_word = False
            else:
                toks.append(Word("".join(buf), dyn))
        buf, dyn, in_word = [], False, False

    def op(o: str):
        nonlocal drop_next_word
        flush()
        drop_next_word = False
        toks.append(_Op(o))

    while i < n:
        c = s[i]
        if c == "\\":
            if i + 1 < n:
                if s[i + 1] == "\n":
                    i += 2
                    continue
                buf.append(s[i + 1])
                in_word = True
                i += 2
            else:
                i += 1
            continue
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                return None
            buf.append(s[i + 1:j])
            in_word = True
            i = j + 1
            continue
        if c == '"':
            res = _read_double(s, i + 1)
            if res is None:
                return None
            j, text, d = res
            buf.append(text)
            dyn = dyn or d
            in_word = True
            i = j
            continue
        if c == "$":
            if i + 1 < n and s[i + 1] == "'":  # $'ansi-c'
                j = _ansi_c_end(s, i + 2)
                if j is None:
                    return None
                buf.append(s[i + 2:j])
                in_word = True
                i = j + 1
                continue
            if i + 1 < n and s[i + 1] == '"':  # $"locale" behaves like "..."
                i += 1
                continue
            end = _expansion_end(s, i)
            if end is None:
                return None
            buf.append(s[i:end])
            dyn = dyn or end > i + 1
            in_word = True
            i = end
            continue
        if c == "`":
            j = _backtick_end(s, i + 1)
            if j is None:
                return None
            buf.append(s[i:j + 1])
            dyn = True
            in_word = True
            i = j + 1
            continue
        if c in " \t\r":
            flush()
            i += 1
            continue
        if c == "\n":
            op("\n")
            i += 1
            continue
        if c == "#" and not in_word:
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in "<>":
            if i + 1 < n and s[i + 1] == "(":  # process substitution <(...) >(...)
                j = _paren_end(s, i + 2)
                if j is None:
                    return None
                buf.append(s[i:j + 1])
                dyn = True
                in_word = True
                i = j + 1
                continue
            if in_word and not dyn and "".join(buf).isdigit():
                buf, in_word = [], False  # "2>file": the digits are a file descriptor
            else:
                flush()
            m = _REDIR.match(s, i)
            redir = m.group(0)
            if redir in ("<<", "<<-"):
                return None  # heredoc: body is not shell words; don't guess
            drop_next_word = True
            i = m.end()
            continue
        if c == "&":
            if s.startswith("&>", i):
                flush()
                drop_next_word = True
                i += 3 if s.startswith("&>>", i) else 2
                continue
            if s.startswith("&&", i):
                op("&&")
                i += 2
            else:
                op("&")
                i += 1
            continue
        if c == "|":
            if s.startswith("||", i):
                op("||")
                i += 2
            elif s.startswith("|&", i):
                op("|&")
                i += 2
            else:
                op("|")
                i += 1
            continue
        if c == ";":
            op(";")
            i += 3 if s.startswith(";;&", i) else 2 if s.startswith((";;", ";&"), i) else 1
            continue
        if c in "()":
            op(c)
            i += 1
            continue
        if c in "*?[":
            dyn = True
        buf.append(c)
        in_word = True
        i += 1
    flush()
    return toks


def _read_double(s: str, i: int):
    """Read a double-quoted string starting after the opening quote.

    Returns (index after closing quote, text, dynamic) or None if unbalanced.
    """
    out: list[str] = []
    dyn = False
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            return i + 1, "".join(out), dyn
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in '"\\$`':
                out.append(nxt)
                i += 2
                continue
            if nxt == "\n":
                i += 2
                continue
            out.append(c)
            i += 1
            continue
        if c == "$":
            end = _expansion_end(s, i)
            if end is None:
                return None
            out.append(s[i:end])
            dyn = dyn or end > i + 1
            i = end
            continue
        if c == "`":
            j = _backtick_end(s, i + 1)
            if j is None:
                return None
            out.append(s[i:j + 1])
            dyn = True
            i = j + 1
            continue
        out.append(c)
        i += 1
    return None


def _expansion_end(s: str, i: int):
    """``s[i]`` is ``$``. Return the index just past the expansion (i+1 for a lone $)."""
    n = len(s)
    if i + 1 >= n:
        return i + 1
    c = s[i + 1]
    if c == "(":
        j = _paren_end(s, i + 2)
        return None if j is None else j + 1
    if c == "{":
        depth, k = 1, i + 2
        while k < n:
            if s[k] == "\\":
                k += 2
                continue
            if s[k] == "{":
                depth += 1
            elif s[k] == "}":
                depth -= 1
                if depth == 0:
                    return k + 1
            k += 1
        return None
    if c.isalpha() or c == "_":
        k = i + 2
        while k < n and (s[k].isalnum() or s[k] == "_"):
            k += 1
        return k
    if c.isdigit() or c in "@*#?$!-":
        return i + 2
    return i + 1


def _paren_end(s: str, i: int):
    """Index of the ``)`` closing a ``(`` that was just before ``s[i]``, or None."""
    depth, n = 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                return None
            i = j + 1
            continue
        if c == '"':
            res = _read_double(s, i + 1)
            if res is None:
                return None
            i = res[0]
            continue
        if c == "`":
            j = _backtick_end(s, i + 1)
            if j is None:
                return None
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _backtick_end(s: str, i: int):
    n = len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "`":
            return i
        i += 1
    return None


def _ansi_c_end(s: str, i: int):
    n = len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "'":
            return i
        i += 1
    return None
