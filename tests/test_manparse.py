from __future__ import annotations

from pathlib import Path

from fluent.core.manparse import decode_roff, option_headers, parse_man

HELP = Path(__file__).parent / "fixtures" / "help"


def names(rel: str) -> set[str]:
    return {n for f in parse_man((HELP / rel).read_text(errors="replace")) for n in f.names}


def test_decode_roff():
    assert decode_roff(r"\fB\-\-create\fR, \fB\-c\fR") == "--create, -c"
    assert decode_roff(r"\-\-[no\-]mailmap") == "--[no-]mailmap"
    assert decode_roff(r"\(aqx\(aq") == "'x'"


def test_git_log_man_completes_the_short_help():
    found = names("git/man/git-log.1")
    assert len(found) > 150
    for flag in ("--follow", "--oneline", "--graph", "--stat", "--decorate", "--no-decorate"):
        assert flag in found


def test_headers_only_never_prose():
    src = ".PP\nUse \\-\\-follow to keep going.\n.PP\n\\-\\-follow\n.RS 4\ntext\n"
    assert option_headers(src) == ["--follow"]


def test_other_dialects():
    assert {"--catenate", "-A", "--create"} <= names("tar/man/tar.1")
    assert {"--relative", "-R", "--delete"} <= names("rsync/man/rsync.1")
    assert {"--abstract-unix-socket", "--data"} <= names("curl/man/curl.1")
    assert "--yes" in names("gh/man/gh-repo-delete.1")
    assert "--add-host" in names("docker/man/docker-run.1")
