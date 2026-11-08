from __future__ import annotations

from pathlib import Path

from fluent.core.manparse import decode_roff, mdoc_text, option_headers, parse_man

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


# A BSD/macOS man page (mdoc macros), shaped like libarchive's bsdtar.1, which is the
# tar that ships with macOS.
MDOC = r"""
.Dd June 3, 2024
.Dt BSDTAR 1
.Sh NAME
.Nm tar
.Sh DESCRIPTION
.Bl -tag -compact -width indent
.It Fl c
Create a new archive containing the specified items.
The long option form is
.Fl Fl create .
.El
.Sh OPTIONS
.Bl -tag -width indent
.It Fl a , Fl Fl auto-compress
Use the archive suffix to decide a set of the format and the compressions.
.It Fl C Ar directory , Fl Fl cd Ar directory , Fl Fl directory Ar directory
In c and r mode, this changes the directory before adding the following files.
.It Fl f Ar file , Fl Fl file Ar file
Read the archive from or write the archive to the specified file.
.It Fl Fl exclude-vcs
Do not process files or directories used by version control systems.
.It Xo
.Fl Fl strip-components
.Ar count
.Xc
Remove the specified number of leading path elements.
.It Fl v , Fl Fl verbose
Produce verbose output.
.El
.Sh COMPATIBILITY
Unlike GNU tar, there is no
.Fl Fl wildcards
option.
"""


def test_mdoc_text():
    assert mdoc_text("Fl a , Fl Fl all") == "-a, --all"
    assert mdoc_text("Fl C Ar dir , Fl Fl cd Ar dir") == "-C dir, --cd dir"
    assert mdoc_text("Fl o Ar key Ns = Ns Ar value") == "-o key=value"


def test_mdoc_man_page_like_macos_tar():
    flags = {n: f for f in parse_man(MDOC) for n in f.names}
    assert {"-a", "--auto-compress", "-C", "--cd", "--directory", "--exclude-vcs",
            "--strip-components", "-v", "--verbose", "--create"} <= set(flags)
    assert flags["--directory"].takes_value and flags["--strip-components"].takes_value
    assert not flags["--verbose"].takes_value
    # an option only mentioned in prose is never read
    assert "--wildcards" not in flags


def test_prose_that_states_an_option_exists():
    src = (".TP\n\\-\\-ssl\\-reqd\nRequire SSL. This option was formerly known as \\-\\-ftp\\-ssl\\-reqd.\n"
           ".TP\n\\-\\-disable\\-eprt\nDo not use EPRT. \\-\\-eprt can be used to explicitly enable EPRT again\n"
           "and \\-\\-no\\-eprt is an alias for\n\\-\\-disable\\-eprt.\n")
    found = {n for f in parse_man(src) for n in f.names}
    assert {"--ssl-reqd", "--ftp-ssl-reqd", "--disable-eprt", "--eprt", "--no-eprt"} <= found
