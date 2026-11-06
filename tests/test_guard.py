"""The guard against real programs: zero false blocks on a corpus of valid commands, and
every typical AI mistake caught with the right fix. Uses the programs installed on the
machine running the tests; programs that are missing are skipped."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from fluent.core.adopt import adopt
from fluent.core.card import Card, Flag, Node
from fluent.core.matcher import check_invocation
from fluent.core.shellsplit import split_command
from fluent.core.store import CardStore
from fluent.glue import guard as guard_mod
from fluent.glue import hooks, state
from fluent.glue.guard import Guard

CORPUS = Path(__file__).parent / "fixtures" / "corpus"
PROGRAMS = [p for p in "git gh docker ffmpeg curl tar jq rsync".split() if shutil.which(p)]


def corpus_lines(name: str) -> list[str]:
    return [ln for ln in (CORPUS / name).read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


@pytest.fixture(scope="module")
def real_store(tmp_path_factory):
    store = CardStore(tmp_path_factory.mktemp("cards"))
    for p in PROGRAMS:
        store.save(adopt(p))
    return store


@pytest.fixture(scope="module")
def real_guard(real_store):
    return Guard(real_store, backend=lambda: "local")


def _uses_only_installed(cmd: str) -> bool:
    known = set("git gh docker ffmpeg curl tar jq rsync".split())
    return all(i.program in PROGRAMS for i in split_command(cmd) if i.program in known)


@pytest.mark.parametrize("cmd", corpus_lines("valid.txt"))
def test_valid_commands_are_never_blocked(real_guard, cmd):
    if not _uses_only_installed(cmd):
        pytest.skip("program not installed")
    verdict = real_guard.check(cmd)
    assert verdict.action not in ("block", "warn"), [(f.token, f.suggestion) for f in verdict.findings]


@pytest.mark.parametrize("line", corpus_lines("invalid.txt"))
def test_typical_mistakes_are_caught(real_guard, line):
    cmd, token, suggestion = (line.split("\t") + ["", ""])[:3]
    if not _uses_only_installed(cmd):
        pytest.skip("program not installed")
    verdict = real_guard.check(cmd)
    assert verdict.action == "block"
    hits = [(f.token, f.suggestion) for f in verdict.findings]
    assert any(t == token and (not suggestion or s == suggestion) for t, s in hits), hits
    assert token in verdict.message and verdict.notice.startswith("🛡️")


def test_destructive_commands_ask_through_hermes(real_guard):
    if "rsync" in PROGRAMS:
        v = real_guard.check("rsync -av --delete src/ dst/")
        assert v.action == "approve" and v.rule_key == "fluent:rsync:-:--delete"
    if "docker" in PROGRAMS:
        v = real_guard.check("docker image prune -a")
        assert v.action == "approve" and v.rule_key == "fluent:docker:image.prune"
        assert real_guard.check("docker stop web").action == "allow"  # Hermes already asks
    if "git" in PROGRAMS:
        assert real_guard.check("git clean -fd").action == "allow"  # Hermes already asks
        assert real_guard.check("git rm file.txt").action == "allow"


def test_modes_and_risk_switch(real_store):
    g = Guard(real_store, backend=lambda: "local")
    if "curl" not in PROGRAMS or "rsync" not in PROGRAMS:
        pytest.skip("needs curl and rsync")
    real_store.set_config("mode", "warn")
    assert g.check("curl --silentt https://x").action == "warn"
    real_store.set_config("mode", "off")
    assert g.check("curl --silentt https://x").action == "allow"
    real_store.set_config("mode", "block")
    real_store.set_config("risk_prompts", False)
    assert g.check("rsync -av --delete a/ b/").action == "allow"
    real_store.set_config("risk_prompts", True)


def test_never_blocks_on_remote_backends_or_changed_binaries(real_store):
    if "curl" not in PROGRAMS:
        pytest.skip("needs curl")
    assert Guard(real_store, backend=lambda: "docker").check("curl --silentt x").action == "allow"
    other = Guard(real_store, backend=lambda: "local", which=lambda p: "/bin/sh")
    assert other.check("curl --silentt x").action == "allow"


# ----------------------------------------------------------------- matcher rules
def _card() -> Card:
    card = Card(program="tool", style="gnu", abbrev_ok=True)
    card.nodes[""] = Node(path=[], confidence="high", subcommands=["run"], flags=[
        Flag(names=["-C", "--dir"], takes_value=True), Flag(names=["--verbose"])])
    card.nodes["run"] = Node(path=["run"], confidence="high", usage="tool run [OPTIONS] IMAGE [COMMAND] [ARG...]",
                             flags=[Flag(names=["--rm"]), Flag(names=["--name"], takes_value=True),
                                    Flag(names=["--network"], takes_value=True)])
    return card


@pytest.mark.parametrize("cmd,tokens", [
    ("tool run --rm img", []),
    ("tool run --rmm img", ["--rmm"]),
    ("tool run --name --weird img", []),  # value of --name, never judged
    ("tool run --net host img", []),  # unique prefix: allowed where the program allows it
    ("tool run img sh -c 'x --anything'", []),  # after IMAGE everything belongs to COMMAND
    ("tool run -- --rmm", []),  # after --
    ("tool run --rm $FLAGS img", []),  # dynamic
    ("tool run --$X img", []),
    ("tool -C dir run --rm img", []),
    ("tool --verbos run img", []),  # prefix of --verbose
    ("tool --verbosity run img", ["--verbosity"]),
    ("tool unknown-sub --whatever", []),  # unknown subcommand: never judged
    ("tool run -z img", []),  # short options are never judged
])
def test_matcher_rules(cmd, tokens):
    inv = split_command(cmd)[0]
    chk = check_invocation(inv, _card())
    assert [f.token for f in chk.findings] == tokens


def test_low_confidence_is_never_judged():
    card = _card()
    card.nodes["run"].confidence = "medium"
    assert check_invocation(split_command("tool run --rmm img")[0], card).findings == []


# ----------------------------------------------------------------- hooks
class Ctx:
    def __init__(self):
        self.posts = []

    def post_message(self, text):
        self.posts.append(text)


@pytest.fixture
def hook_env(tmp_path, monkeypatch):
    store = CardStore(tmp_path)
    store.save(_card_with_path())
    monkeypatch.setattr(hooks, "store", lambda: store)
    monkeypatch.setattr(state, "store", lambda: store)
    monkeypatch.setattr(hooks, "_guards", {})
    g = Guard(store, backend=lambda: "local", which=lambda p: "/fake/tool")
    monkeypatch.setattr(hooks, "guard", lambda: g)
    ctx = Ctx()
    monkeypatch.setattr(hooks, "_ctx", ctx)
    monkeypatch.setattr(hooks, "notify", lambda text: ctx.posts.append(text) if text else None)
    return store, ctx


def _card_with_path() -> Card:
    card = _card()
    card.path = "/fake/tool"
    return card


def test_pre_tool_call_blocks_and_counts(hook_env, monkeypatch):
    store, ctx = hook_env
    monkeypatch.setattr(guard_mod.Guard, "_fresh", lambda self, card, ttl=10.0: True)
    out = hooks.on_pre_tool_call(tool_name="terminal", args={"command": "tool run --rmm img"},
                                 tool_call_id="c1")
    assert out["action"] == "block" and "--rmm" in out["message"] and "--rm" in out["message"]
    assert ctx.posts and ctx.posts[0].startswith("🛡️ fluent caught `--rmm`")
    c = store.counters()
    assert c["caught"] == 1 and c["tokens_saved"] > 0
    assert hooks.on_pre_tool_call(tool_name="terminal", args={"command": "tool run --rm img"}) is None
    assert hooks.on_pre_tool_call(tool_name="read_file", args={"path": "x"}) is None


def test_pre_tool_call_never_raises(hook_env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(hooks, "guard", boom)
    assert hooks.on_pre_tool_call(tool_name="terminal", args={"command": "tool run"}) is None


def test_warn_mode_appends_note_to_output(hook_env, monkeypatch):
    store, ctx = hook_env
    store.set_config("mode", "warn")
    monkeypatch.setattr(guard_mod.Guard, "_fresh", lambda self, card, ttl=10.0: True)
    assert hooks.on_pre_tool_call(tool_name="terminal", args={"command": "tool run --rmm x"},
                                  tool_call_id="c9") is None
    out = hooks.on_transform_terminal_output(command="tool run --rmm x", output="error: unknown flag",
                                             tool_call_id="c9")
    assert out.startswith("error: unknown flag") and "fluent: `--rmm`" in out
    assert hooks.on_transform_terminal_output(output="x", tool_call_id="c9") is None


def test_post_tool_call_offers_to_learn_once(hook_env, monkeypatch):
    store, ctx = hook_env
    monkeypatch.setattr(hooks, "_offered", set())
    monkeypatch.setattr(hooks.shutil, "which", lambda p: "/usr/bin/" + p)
    result = json.dumps({"output": "curl: option --silentt: is unknown", "exit_code": 2})
    hooks.on_post_tool_call(tool_name="terminal", args={"command": "curl --silentt x"},
                            result=result, session_id="s1")
    hooks.on_post_tool_call(tool_name="terminal", args={"command": "curl --silentt x"},
                            result=result, session_id="s1")
    assert len(ctx.posts) == 1 and "/fluent adopt curl" in ctx.posts[0]
    store.set_config("not_now", ["wget"])
    hooks.on_post_tool_call(tool_name="terminal", args={"command": "wget --x y"},
                            result=json.dumps({"output": "wget: unrecognized option", "exit_code": 2}),
                            session_id="s1")
    assert len(ctx.posts) == 1


# ----------------------------------------------------------------- review regressions
@pytest.mark.parametrize("cmd", [
    "tool $SUB --whatever",          # subcommand only known at run time: never judged
    'tool "$(pick)" --whatever',
])
def test_dynamic_subcommand_is_never_judged(cmd):
    assert check_invocation(split_command(cmd)[0], _card()).findings == []


def test_git_accepts_no_prefix_negation():
    card = Card(program="git", style="git", abbrev_ok=True)
    card.nodes[""] = Node(path=[], confidence="high", subcommands=["log"])
    card.nodes["log"] = Node(path=["log"], confidence="high", flags=[Flag(names=["--follow"])])
    assert check_invocation(split_command("git log --no-follow")[0], card).findings == []
    assert [f.token for f in check_invocation(split_command("git log --no-folow")[0], card).findings] == ["--no-folow"]


def test_find_exec_hands_the_rest_to_another_program():
    card = Card(program="find", style="gnu", abbrev_ok=True)
    card.nodes[""] = Node(path=[], confidence="high", flags=[Flag(names=["--help"]), Flag(names=["--version"])])
    assert check_invocation(split_command("find . -exec git log --oneline {} ;")[0], card).findings == []
    assert check_invocation(split_command("find . --versoin")[0], card).findings


@pytest.mark.parametrize("cmd,asks", [
    ("docker rm restart-policy-test", False),
    ("docker volume rm stop-data", False),
    ("docker --context prod stop web", True),
    ("docker compose -f x.yml down", True),
])
def test_core_rule_needs_the_verb_right_after_docker(cmd, asks):
    from fluent.core.risk import core_already_asks
    assert core_already_asks(cmd) is asks


def test_warn_mode_keeps_the_destructive_prompt(real_store):
    if "rsync" not in PROGRAMS:
        pytest.skip("needs rsync")
    real_store.set_config("mode", "warn")
    try:
        v = Guard(real_store, backend=lambda: "local").check("rsync -av --delete --exlude=x a/ b/")
        assert v.action == "approve" and "--exlude" in v.message
    finally:
        real_store.set_config("mode", "block")


# ----------------------------------------------------------------- maintainer review regressions
def test_docker_rule_is_linear_time():
    import time
    from fluent.core.risk import core_already_asks
    start = time.perf_counter()
    assert core_already_asks("docker " + "-a " * 200 + "system prune") is False
    assert core_already_asks("docker " + "--log-level debug " * 50 + "stop web") is True
    assert time.perf_counter() - start < 0.05


def test_path_qualified_program_is_not_judged_against_another_binary(real_store):
    if "curl" not in PROGRAMS:
        pytest.skip("needs curl")
    g = Guard(real_store, backend=lambda: "local")
    assert g.check("./curl --silentt x").action == "allow"
    assert g.check("/opt/other/curl --silentt x").action == "allow"
    real = shutil.which("curl")
    assert g.check(f"{real} --silentt x").action == "block"
