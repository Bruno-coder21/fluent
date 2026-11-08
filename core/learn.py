"""Recognize "you used an option that doesn't exist" in a program's output."""

from __future__ import annotations

import re

_OPTION_ERRORS = re.compile(
    r"unrecognized option|unknown option|unknown flag|flag provided but not defined|"
    r"invalid option|illegal option|no such option|option .{0,40} is unknown|"
    r"unknown switch|is not a git command|unknown command|Option not found|"
    r"Unrecognized option '|option .{0,40} is not supported",
    re.I,
)

# Never offered for adoption: shells, interpreters and wrappers whose "options" are
# really someone else's program, plus tools where a help run is pointless.
NEVER_SUGGEST = frozenset((
    "sh", "bash", "zsh", "dash", "fish", "ksh", "python", "python3", "node", "deno", "bun",
    "ruby", "perl", "php", "sudo", "doas", "env", "xargs", "timeout", "nohup", "nice",
    "watch", "time", "stdbuf", "ionice", "exec", "command",
))


def looks_like_option_error(output: str) -> bool:
    return bool(output) and bool(_OPTION_ERRORS.search(output[-4000:]))
