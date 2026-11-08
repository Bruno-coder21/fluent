"""Adoption with fake programs: proves fluent only ever runs help calls."""

from __future__ import annotations

import os
import shutil
import stat
import textwrap
from pathlib import Path

import pytest

from fluent.core import adopt as adopt_mod
from fluent.core.adopt import AdoptError, Adopter, adopt

FAKE = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "{log}"
    case "$*" in
      "--version") echo "faketool version 1.2.3";;
      "--help") cat <<'EOF'
    Usage:  faketool [OPTIONS] COMMAND

    A fake tool for tests

    Commands:
      list        List things
      delete      Delete a thing
      deploy      Deploy everything

    Options:
      -v, --verbose        Be loud
      -c, --config string  Config file

    Run 'faketool COMMAND --help' for more information on a command.
    EOF
      ;;
      "list --help") printf 'Usage:  faketool list [OPTIONS]\\n\\nList things\\n\\nOptions:\\n  -a, --all   Show all\\n  -q, --quiet  Only ids\\n';;
      "delete --help") printf 'Usage:  faketool delete [OPTIONS] NAME\\n\\nDelete a thing\\n\\nOptions:\\n  -f, --force   Skip the confirmation prompt\\n';;
      "deploy --help") printf 'Usage:  faketool deploy [OPTIONS]\\n\\nDeploy everything\\n\\nOptions:\\n  --env string   Target\\n';;
      *) echo "REAL RUN: $*" >> "{marker}"; exit 3;;
    esac
""")


@pytest.fixture
def fake_tool(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    marker = tmp_path / "REAL_RUN"
    script = bindir / "faketool"
    script.write_text(FAKE.format(log=log, marker=marker))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return {"log": log, "marker": marker}


def test_adopt_fake_tool(fake_tool):
    stages = []
    card = adopt("faketool", progress=lambda s, i: stages.append(s), man_dirs=[])
    assert card.version == "1.2.3"
    assert card.style == "cobra"
    assert set(card.root.subcommands) == {"list", "delete", "deploy"}
    assert card.nodes["delete"].risk == "destroy"
    assert card.nodes["list"].risk == "read"
    assert card.nodes["deploy"].risk == "change"
    assert card.nodes["delete"].flags[0].destroy is True
    assert card.nodes["list"].confidence == "high"
    assert stages[0] == "start" and stages[-1] == "done"
    assert not fake_tool["marker"].exists(), "fluent must never run a real command"
    calls = fake_tool["log"].read_text().splitlines()
    assert all(c.endswith("--help") or c == "--version" for c in calls)


def test_missing_program():
    with pytest.raises(AdoptError, match="can't find"):
        adopt("definitely-not-a-program-xyz")


def test_program_without_readable_help(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    prog = bindir / "silent"
    prog.write_text("#!/bin/sh\nexit 0\n")
    prog.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(AdoptError, match="didn't print a help"):
        adopt("silent", man_dirs=[])


def test_slow_help_is_cut_and_marked_partial(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    prog = bindir / "slowtool"
    prog.write_text(textwrap.dedent("""\
        #!/bin/sh
        case "$*" in
          "--help") printf 'Usage:  slowtool [OPTIONS] COMMAND\\n\\nCommands:\\n  a   A\\n  b   B\\n\\nOptions:\\n  -x, --xx   X\\n\\nRun '"'"'slowtool COMMAND --help'"'"' for more information on a command.\\n';;
          *) sleep 30;;
        esac
    """))
    prog.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(adopt_mod, "CALL_TIMEOUT", 0.5)
    card = Adopter("slowtool", man_dirs=[], budget=3).run()
    assert card.partial is True
    assert "a" not in card.nodes  # never guessed


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_git_merges_man_pages():
    card = adopt("git")
    log = card.nodes.get("log")
    assert log is not None
    if "man" in log.sources:
        assert "--oneline" in log.flag_names()
        assert log.confidence == "high"
    assert "filter-branch" in card.root.subcommands
    assert card.nodes["rm"].risk == "change"
    assert card.nodes["clean"].risk == "change"


@pytest.mark.parametrize("name", ["/usr/bin/git", "./tool", "../x", "-rf"])
def test_adopt_takes_names_not_paths(name):
    with pytest.raises(AdoptError, match="name as you'd type it"):
        adopt(name)


def test_home_made_script_subcommands_are_never_run(tmp_path, monkeypatch):
    """A script that lists "commands" but only checks --help as $1 must not be explored."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "WIPED"
    prog = bindir / "mytool"
    prog.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        if [ "$1" = "--help" ]; then
          printf 'mytool - my tool\\n\\nOptions:\\n  -v, --verbose   Be loud\\n  -q, --quiet     Quiet\\n  --help          Help\\n\\nCommands:\\n  wipe    Wipe everything\\n  list    List things\\n'
          exit 0
        fi
        if [ "$1" = "wipe" ]; then touch "{marker}"; fi
    """))
    prog.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    card = adopt("mytool", man_dirs=[])
    assert not marker.exists(), "a subcommand of a home-made script was executed"
    assert "wipe" not in card.nodes


def test_error_text_is_not_a_version(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    prog = bindir / "nover"
    prog.write_text(textwrap.dedent("""\
        #!/bin/sh
        case "$1" in
          --help) printf 'Usage: nover [OPTION]\\n  -a, --all   All\\n  -b, --bee   Bee\\n  -c, --cee   Cee\\n';;
          *) echo "nover: unrecognized option '$1'"; exit 2;;
        esac
    """))
    prog.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    assert adopt("nover", man_dirs=[]).version == ""


# A tar shaped like macOS's: a short --help that lists only a few long options, and the
# full list in an mdoc man page.
BSDISH = textwrap.dedent("""\
    #!/bin/sh
    case "$*" in
      "--version") echo "bsdish 3.7.2 - libarchive 3.7.2";;
      "--help") cat <<'EOF'
    bsdish: manipulate archive files
    First option must be a mode specifier:
      -c Create  -t List  -x Extract
    Common Options:
      -b #  Use # 512-byte records per I/O block
      -f <filename>  Location of archive
      -v    Verbose
    Create: bsdish -c [options] [<file> | <dir>]
      -z, -j, -J, --lzma  Compress archive with gzip/bzip2/xz/lzma
      --format {{ustar|pax|cpio|shar}}  Select archive format
      --exclude <pattern>  Skip files that match pattern
    EOF
      ;;
      *) echo "REAL RUN: $*" >> "{marker}"; exit 3;;
    esac
""")


@pytest.fixture
def bsdish(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "bsdish"
    script.write_text(BSDISH.format(marker=tmp_path / "REAL_RUN"))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    mandir = tmp_path / "man"
    (mandir / "man1").mkdir(parents=True)
    return mandir


def _findings(card, command):
    from fluent.core.matcher import check_invocation
    from fluent.core.shellsplit import split_command
    return [f for inv in split_command(command) for f in check_invocation(inv, card).findings]


def test_macos_style_tar_reads_its_mdoc_man_page(bsdish):
    from test_manparse import MDOC
    (bsdish / "man1" / "bsdish.1").write_text(MDOC)
    card = adopt("bsdish", man_dirs=[str(bsdish)])
    assert card.root.confidence == "high"
    for ok in ("bsdish -xf a.tar --strip-components 1 -C out",
               "bsdish --create --file a.tar --verbose dir",
               "bsdish --exclude-vcs -czf a.tgz ."):
        assert _findings(card, ok) == [], ok
    found = _findings(card, "bsdish -xf a.tar --strip-componets 1")
    assert [f.suggestion for f in found] == ["--strip-components"]


def test_unreadable_man_page_never_blocks(bsdish):
    # The help is only a summary and the full manual can't be read: not certain enough.
    (bsdish / "man1" / "bsdish.1").write_text("nothing here a man reader understands\n")
    card = adopt("bsdish", man_dirs=[str(bsdish)])
    assert card.root.confidence == "medium"
    assert _findings(card, "bsdish -xf a.tar --strip-components 1") == []


def test_rules_read_from_the_programs_own_docs():
    from fluent.core.adopt import negation_hint, option_prefixes
    from fluent.core.manparse import decode_roff, read_man_file
    fix = Path(__file__).parent / "fixtures" / "help"
    # rsync --help: "--no-OPTION  turn off an implied OPTION (e.g. --no-D)"
    assert negation_hint((fix / "rsync" / "root.txt").read_text())
    # curl's man page: "all boolean options are ... disabled with --no-option" and
    # 'if the option name is prefixed with "--expand-"'
    curl_man = decode_roff(read_man_file(fix / "curl" / "man" / "curl.1"))
    assert negation_hint(curl_man)
    assert option_prefixes(curl_man) == ["--expand-"]
    # GNU tar documents its own --no-* options one by one: no general rule
    assert not negation_hint(decode_roff(read_man_file(fix / "tar" / "man" / "tar.1")))
