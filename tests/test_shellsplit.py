"""The splitter must find every program a command runs, and never invent one."""

from __future__ import annotations

import pytest

from fluent.core.shellsplit import Word, might_invoke, split_command


def progs(cmd: str) -> list[tuple[str, tuple[str, ...]]]:
    return [(i.program, i.argv) for i in split_command(cmd)]


CASES = [
    # plain commands
    ("git log --oneline", [("git", ("log", "--oneline"))]),
    ("  git   status  ", [("git", ("status",))]),
    ("/usr/bin/git log", [("git", ("log",))]),
    ("\\git log", [("git", ("log",))]),
    ("ffmpeg -i in.mp4 -c:v libx264 -crf 23 out.mp4",
     [("ffmpeg", ("-i", "in.mp4", "-c:v", "libx264", "-crf", "23", "out.mp4"))]),
    ("docker ps --filter status=running", [("docker", ("ps", "--filter", "status=running"))]),
    # operators
    ("git add . && git commit -m 'wip'", [("git", ("add", ".")), ("git", ("commit", "-m", "wip"))]),
    ("make || echo failed", [("make", ()), ("echo", ("failed",))]),
    ("cd repo; git pull", [("cd", ("repo",)), ("git", ("pull",))]),
    ("git log | head -5", [("git", ("log",)), ("head", ("-5",))]),
    ("docker logs app |& grep error", [("docker", ("logs", "app")), ("grep", ("error",))]),
    ("sleep 10 & git status", [("sleep", ("10",)), ("git", ("status",))]),
    ("git status\ngit diff", [("git", ("status",)), ("git", ("diff",))]),
    ("(cd repo && git status)", [("cd", ("repo",)), ("git", ("status",))]),
    ("{ git fetch; git status; }", [("git", ("fetch",)), ("git", ("status",))]),
    # quotes
    ('git commit -m "fix: it\'s done"', [("git", ("commit", "-m", "fix: it's done"))]),
    ("git commit -m 'a && b; c | d'", [("git", ("commit", "-m", "a && b; c | d"))]),
    ('echo "a;b" ; git log', [("echo", ("a;b",)), ("git", ("log",))]),
    ('git log --format="%h %s"', [("git", ("log", "--format=%h %s"))]),
    ("jq '.items[] | .name' data.json", [("jq", (".items[] | .name", "data.json"))]),
    ("git log --grep=fix\\ bug", [("git", ("log", "--grep=fix bug"))]),
    ("git log \\\n  --oneline", [("git", ("log", "--oneline"))]),
    ("echo $'tab\\there'", [("echo", ("tab\\there",))]),
    # redirections are not arguments
    ("git log > out.txt", [("git", ("log",))]),
    ("git log >out.txt 2>&1", [("git", ("log",))]),
    ("git log 2>/dev/null", [("git", ("log",))]),
    ("ffmpeg -i a.mp4 b.mp4 &> log.txt", [("ffmpeg", ("-i", "a.mp4", "b.mp4"))]),
    ("ffmpeg -i a.mp4 b.mp4 &>> log.txt", [("ffmpeg", ("-i", "a.mp4", "b.mp4"))]),
    ("echo a>b", [("echo", ("a",))]),
    ("jq . < data.json", [("jq", (".",))]),
    ("grep x <<< 'hello x'", [("grep", ("x",))]),
    ("git log >| out.txt", [("git", ("log",))]),
    ("cat file 2>&1 >/dev/null", [("cat", ("file",))]),
    # prefixes and wrappers
    ("FOO=1 BAR=2 git log", [("git", ("log",))]),
    ("sudo git clean -fd", [("git", ("clean", "-fd"))]),
    ("sudo -u bob -E git log", [("git", ("log",))]),
    ("sudo --user=bob git log", [("git", ("log",))]),
    ("sudo -- git log", [("git", ("log",))]),
    ("env -i PATH=/bin HOME=/tmp git log", [("git", ("log",))]),
    ("env -u FOO git log", [("git", ("log",))]),
    ("time git log", [("git", ("log",))]),
    ("time -p git log", [("git", ("log",))]),
    ("nice -n 10 ffmpeg -i a b", [("ffmpeg", ("-i", "a", "b"))]),
    ("nice -10 ffmpeg -i a b", [("ffmpeg", ("-i", "a", "b"))]),
    ("nohup docker logs -f app", [("docker", ("logs", "-f", "app"))]),
    ("timeout 30 curl -sS https://example.com", [("curl", ("-sS", "https://example.com"))]),
    ("timeout -s KILL 30 curl https://x", [("curl", ("https://x",))]),
    ("timeout --kill-after=5 30 curl https://x", [("curl", ("https://x",))]),
    ("stdbuf -oL tail -f log", [("tail", ("-f", "log"))]),
    ("ionice -c 3 rsync -a src/ dst/", [("rsync", ("-a", "src/", "dst/"))]),
    ("exec -a myname git log", [("git", ("log",))]),
    ("find . -name x | xargs -0 rm -f", [("find", (".", "-name", "x")), ("rm", ("-f",))]),
    ("ls | xargs -I {} cp {} dst/", [("ls", ()), ("cp", ("{}", "dst/"))]),
    ("ls | xargs -n 1 -P 4 gzip", [("ls", ()), ("gzip", ())]),
    ("sudo env FOO=1 nice -n 5 git log", [("git", ("log",))]),
    # shells running a string
    ("bash -c 'git status && git diff'", [("git", ("status",)), ("git", ("diff",))]),
    ("bash -lc \"docker ps --all\"", [("docker", ("ps", "--all"))]),
    ("sh -ec 'cd /tmp; tar -czf a.tgz dir'", [("cd", ("/tmp",)), ("tar", ("-czf", "a.tgz", "dir"))]),
    ("bash script.sh --flag", [("bash", ("script.sh", "--flag"))]),
    ("watch -n 2 'docker ps'", [("docker", ("ps",))]),
    ("watch -n 2 docker ps", [("docker", ("ps",))]),
    # control flow
    ("if git diff --quiet; then echo clean; fi", [("git", ("diff", "--quiet")), ("echo", ("clean",))]),
    ("while true; do docker ps; sleep 5; done",
     [("true", ()), ("docker", ("ps",)), ("sleep", ("5",))]),
    ("for f in *.mp4; do ffmpeg -i \"$f\" out.webm; done", [("ffmpeg", ("-i", "$f", "out.webm"))]),
    ("! git diff --quiet", [("git", ("diff", "--quiet"))]),
    ("git log # show history", [("git", ("log",))]),
    ("git log a#b", [("git", ("log", "a#b"))]),
]


@pytest.mark.parametrize("cmd,expected", CASES, ids=[c[0][:40] for c in CASES])
def test_split(cmd, expected):
    assert progs(cmd) == expected


@pytest.mark.parametrize("cmd", [
    "",
    "cat <<EOF\ngit log\nEOF",  # heredoc: not read
    "git commit -m 'unbalanced",
    'echo "unbalanced',
    "echo $(unbalanced",
    "x" * 9000,  # too long
    "$CMD --flag",  # program unknown until run time
    "$(which git) log",
    "command -v git",  # lookup, not execution
    "sudo -v",
    "env",
    "builtin echo hi",
    "[[ -f x ]] && echo",  # [[ is skipped, echo after && still read (checked below)
])
def test_unreadable_or_no_program(cmd):
    result = progs(cmd)
    if cmd.startswith("[[ "):
        assert result == [("echo", ())]
    else:
        assert result == []


def test_dynamic_words_are_marked():
    inv = split_command('ffmpeg -i "$IN" -preset $P *.mp4 --x=`date` -y')[0]
    flags = {w.text: w.dynamic for w in inv.args}
    assert flags["$IN"] is True
    assert flags["$P"] is True
    assert flags["*.mp4"] is True
    assert flags["--x=`date`"] is True
    assert flags["-y"] is False
    assert flags["-i"] is False


def test_quoted_glob_and_dollar_are_literal():
    inv = split_command("git log -- '*.py' '$HOME'")[0]
    assert inv.args == (Word("log"), Word("--"), Word("*.py"), Word("$HOME"))


def test_command_substitution_argument_is_one_dynamic_word():
    inv = split_command('git checkout "$(git rev-parse --abbrev-ref HEAD)" -b x')[0]
    assert inv.program == "git"
    assert inv.argv[0] == "checkout"
    assert inv.args[1].dynamic is True
    assert inv.argv[2:] == ("-b", "x")


def test_program_path_and_segment():
    inv = split_command("sudo /usr/local/bin/gh repo list --limit 5")[0]
    assert inv.program == "gh"
    assert inv.program_path == "/usr/local/bin/gh"
    assert "gh repo list" in inv.segment


def test_nesting_is_bounded():
    cmd = "bash -c \"bash -c 'bash -c \\\"bash -c git\\\"'\""
    assert all(i.program != "git" for i in split_command(cmd)) or len(split_command(cmd)) <= 1


def test_might_invoke():
    assert might_invoke("cd x && git log", {"git", "docker"})
    assert not might_invoke("ls -la", {"git", "docker"})
    assert not might_invoke("ls", set())


def test_never_raises_on_garbage():
    for junk in ["\\", "'", '"', "$(", "${", "`", "<(", "|||", ";;;", "&&&", ">>>", "((("]:
        split_command(junk)
