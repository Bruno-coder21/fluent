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
          "--help") printf 'Usage:  slowtool [OPTIONS] COMMAND\\n\\nCommands:\\n  a   A\\n  b   B\\n\\nOptions:\\n  -x, --xx   X\\n';;
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
