"""Help parsing against real help text captured from the programs on the dev machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from fluent.core.helpparse import parse_help, parse_list_lines, parse_option_spec

HELP = Path(__file__).parent / "fixtures" / "help"


def load(rel: str, program: str):
    return parse_help((HELP / rel).read_text(errors="replace"), program)


def flag_index(parsed):
    return {n: f for f in parsed.flags + parsed.inherited for n in f.names}


# ----------------------------------------------------------------- single lines
@pytest.mark.parametrize("line,style,names,value", [
    ("  -a, --all             Show all containers", "cobra", ["-a", "--all"], False),
    ("  -f, --filter filter   Filter output", "cobra", ["-f", "--filter"], True),
    ("      --format string   Format output", "cobra", ["--format"], True),
    ("  -L, --limit int   Maximum number", "cobra", ["-L", "--limit"], True),
    ("  -R, --repo [HOST/]OWNER/REPO   Select another repository", "cobra", ["-R", "--repo"], True),
    ("  -C, --directory=DIR        change to directory DIR", "gnu", ["-C", "--directory"], True),
    ("      --block-size=SIZE      scale sizes", "gnu", ["--block-size"], True),
    ("  -A, --catenate, --concatenate   append tar files", "gnu", ["-A", "--catenate", "--concatenate"], False),
    ("--verbose, -v            increase verbosity", "gnu", ["--verbose", "-v"], False),
    ("    -q, --[no-]quiet      suppress diff output", "git", ["-q", "--quiet", "--no-quiet"], False),
    ("    -e, --exclude <pattern>", "git", ["-e", "--exclude"], True),
    ("    --[no-]decorate[=...] decorate options", "git", ["--decorate", "--no-decorate"], None),
    ("     --aws-sigv4 <provider1[:provider2]> Use AWS V4 signature", "gnu", ["--aws-sigv4"], True),
    ("     --anyauth     Pick any authentication method", "gnu", ["--anyauth"], False),
    ("      --arg name value      set $name to value", "gnu", ["--arg"], True),
    ("    -x | -X  ignored files", "git", ["-x", "-X"], False),
])
def test_option_line(line, style, names, value):
    flag = parse_option_spec(line, style)
    assert flag is not None
    assert flag.names == names
    assert flag.takes_value is value


@pytest.mark.parametrize("line", [
    "  - by number, e.g. \"123\";",
    "Usage: curl [options...] <url>",
    "  $ gh pr create --fill",
    "just prose with --flag inside",
    "",
])
def test_not_option_lines(line):
    assert parse_option_spec(line) is None


# ----------------------------------------------------------------- whole programs
def test_gh_repo_delete():
    p = load("gh/repo_delete.txt", "gh")
    assert p.style == "cobra"
    assert p.usage.startswith("gh repo delete")
    assert p.summary == "Delete a GitHub repository."
    idx = flag_index(p)
    assert idx["--yes"].takes_value is False
    assert "--help" in idx


def test_gh_pr_lists_subcommands():
    p = load("gh/pr.txt", "gh")
    subs = [s for s, _ in p.subcommands]
    for name in ("create", "list", "merge", "checkout", "update-branch"):
        assert name in subs
    assert flag_index(p)["--repo"].takes_value is True


def test_gh_root_alias_commands_are_commands():
    p = load("gh/root.txt", "gh")
    subs = [s for s, _ in p.subcommands]
    assert "co" in subs and "repo" in subs and "pr" in subs
    assert p.aliases == []


def test_docker_root():
    p = load("docker/root.txt", "docker")
    assert p.style == "cobra"
    subs = [s for s, _ in p.subcommands]
    for name in ("run", "ps", "image", "compose", "system", "volume"):
        assert name in subs
    glob = {n for f in p.inherited for n in f.names}
    assert {"--context", "-H", "--host"} <= glob


def test_docker_ps_and_aliases():
    p = load("docker/ps.txt", "docker")
    idx = flag_index(p)
    assert idx["--all"].takes_value is False
    assert idx["--filter"].takes_value is True
    assert idx["-n"].takes_value is True
    assert "container ls" in p.aliases


def test_docker_run():
    p = load("docker/run.txt", "docker")
    idx = flag_index(p)
    assert len(p.flags) > 80
    assert idx["--rm"].takes_value is False
    assert idx["--publish"].takes_value is True
    assert p.usage.startswith("docker run [OPTIONS] IMAGE")


def test_ffmpeg_full_help():
    p = load("ffmpeg/full.txt", "ffmpeg")
    assert p.style == "ffmpeg"
    idx = flag_index(p)
    assert len(idx) > 1000
    assert idx["-crf"].takes_value is True
    assert idx["-preset"].takes_value is True
    assert idx["-c"].takes_value is True
    assert idx["-y"].takes_value is False
    assert "-vf" in idx and "-ss" in idx and "--help" in idx
    assert "--crf" not in idx


def test_curl_all():
    p = load("curl/all.txt", "curl")
    idx = flag_index(p)
    assert len(p.flags) > 200
    assert idx["--data"].takes_value is True and "-d" in idx
    assert idx["--silent"].takes_value is False and "-s" in idx


def test_tar():
    idx = flag_index(load("tar/root.txt", "tar"))
    assert idx["--create"].takes_value is False
    assert idx["--file"].takes_value is True and "-f" in idx
    assert "--delete" in idx


def test_jq_and_rsync():
    jq = flag_index(load("jq/root.txt", "jq"))
    assert jq["--arg"].takes_value is True
    assert jq["--raw-output"].takes_value is False
    rs = flag_index(load("rsync/root.txt", "rsync"))
    assert rs["--archive"].takes_value is False
    assert rs["--exclude"].takes_value is True
    assert "--delete" in rs


def test_git_subcommand_help_is_partial_but_parsed():
    p = load("git/clean.txt", "git")
    assert p.style == "git"
    assert p.summary == ""
    idx = flag_index(p)
    assert {"-f", "--force", "--no-force"} <= set(idx)
    assert idx["--exclude"].takes_value is True


def test_list_lines():
    assert parse_list_lines("add\nbranch\n\nNot A Command\nlog\nadd\n") == ["add", "branch", "log"]
