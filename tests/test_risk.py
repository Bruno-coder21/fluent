from __future__ import annotations

import pytest

from fluent.core.card import Flag, Node
from fluent.core.risk import classify_node, core_already_asks, is_destroy_flag


@pytest.mark.parametrize("program,path,summary,risk", [
    ("gh", ["repo", "delete"], "Delete a GitHub repository.", "destroy"),
    ("gh", ["repo", "list"], "List repositories owned by user or organization", "read"),
    ("gh", ["pr", "create"], "Create a pull request", "change"),
    ("docker", ["ps"], "List containers", "read"),
    ("docker", ["image", "prune"], "Remove unused images", "destroy"),
    ("docker", ["rm"], "Remove one or more containers", "destroy"),
    ("docker", ["run"], "Create and run a new container from an image", "change"),
    ("git", ["status"], "", "read"),
    ("git", ["clean"], "", "change"),  # override: nothing is deleted without -f, and Hermes asks for -f
    ("git", ["rm"], "", "change"),  # override: git keeps history, refuses modified files
    ("git", ["commit"], "", "change"),
    ("git", ["ls-files"], "", "read"),
    ("jq", [], "", "read"),
    ("ffmpeg", [], "", "change"),
])
def test_classify_node(program, path, summary, risk):
    assert classify_node(program, Node(path=path, summary=summary))[0] == risk


def test_network():
    assert classify_node("git", Node(path=["push"]))[1] is True
    assert classify_node("git", Node(path=["status"]))[1] is False
    assert classify_node("gh", Node(path=["pr", "list"]))[1] is True


@pytest.mark.parametrize("names,desc,destroy", [
    (["--delete"], "delete extraneous files from dest dirs", True),
    (["--yes"], "Confirm deletion without prompting", True),
    (["-f", "--force"], "force checkout (throw away local modifications)", True),
    (["-y"], "overwrite output files", False),
    (["-n", "--dry-run"], "dry run, do not delete anything", False),
    (["--delete-branch"], "Delete the local and remote branch after merge", False),
    (["-p", "--prune"], "prune remote-tracking branches no longer on remote", False),
    (["-v", "--verbose"], "increase verbosity", False),
])
def test_destroy_flags(names, desc, destroy):
    assert is_destroy_flag(Flag(names=names, desc=desc)) is destroy


@pytest.mark.parametrize("cmd,asks", [
    ("git reset --hard HEAD~1", True),
    ("git reset --ha", True),
    ("git push --force origin main", True),
    ("git push -f", True),
    ("git clean -fd", True),
    ("git branch -D old", True),
    ("docker stop web", True),
    ("docker compose down", True),
    ("git push origin main", False),
    ("git branch -d merged", False),
    ("gh repo delete owner/x --yes", False),
    ("docker image prune -a", False),
])
def test_core_already_asks(cmd, asks):
    assert core_already_asks(cmd) is asks
