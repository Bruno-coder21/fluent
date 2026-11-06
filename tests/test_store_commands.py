"""Card store (save, forget, undo) and the /fluent command with a fake Hermes ctx."""

from __future__ import annotations

import pytest

from fluent.core.card import Card, Flag, Node
from fluent.core.store import CardStore
from fluent.glue import commands, state


def make_card(program="tool", version="1.0") -> Card:
    card = Card(program=program, version=version, style="cobra")
    card.nodes[""] = Node(path=[], flags=[Flag(names=["-v", "--verbose"])], subcommands=["rm", "ls"])
    card.nodes["rm"] = Node(path=["rm"], summary="Remove things", risk="destroy",
                            flags=[Flag(names=["-f", "--force"], destroy=True, desc="no prompt")])
    card.nodes["ls"] = Node(path=["ls"], summary="List things", risk="read")
    return card


# ----------------------------------------------------------------- store
def test_card_roundtrip(tmp_path):
    s = CardStore(tmp_path)
    s.save(make_card())
    loaded = s.load("tool")
    assert loaded.nodes["rm"].flags[0].names == ["-f", "--force"]
    assert loaded.nodes["rm"].risk == "destroy"
    assert s.programs() == ["tool"]


def test_forget_and_undo(tmp_path):
    s = CardStore(tmp_path)
    s.save(make_card())
    assert s.forget("tool") is True
    assert s.load("tool") is None
    assert s.undo()["op"] == "forget"
    assert s.load("tool") is not None
    assert s.undo()["op"] == "adopt"  # undo the adoption itself
    assert s.load("tool") is None
    assert s.undo() is None


def test_readopt_then_undo_restores_previous_card(tmp_path):
    s = CardStore(tmp_path)
    s.save(make_card(version="1.0"))
    s.save(make_card(version="2.0"))
    assert s.load("tool").version == "2.0"
    s.undo()
    assert s.load("tool").version == "1.0"


def test_cache_sees_external_changes(tmp_path):
    s = CardStore(tmp_path)
    s.save(make_card(version="1.0"))
    assert s.load("tool").version == "1.0"
    other = CardStore(tmp_path)
    other.save(make_card(version="3.0"))
    import os
    p = s.card_path("tool")
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    assert s.load("tool").version == "3.0"


# ----------------------------------------------------------------- /fluent
class FakeMessage:
    def __init__(self, log):
        self.ok = True
        self.log = log

    def edit(self, text):
        self.log.append(("edit", text))
        return {"ok": True}


class FakeCtx:
    def __init__(self, live=True):
        self.live = live
        self.log = []
        self.commands = {}
        self.hooks = []

    def post_message(self, text):
        self.log.append(("post", text))
        if not self.live:
            class Refused:
                ok = False
            return Refused()
        return FakeMessage(self.log)

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def register_hook(self, name, cb):
        self.hooks.append(name)


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    s = CardStore(tmp_path)
    monkeypatch.setattr(commands, "store", lambda: s)
    monkeypatch.setattr(state, "store", lambda: s)
    return s


def test_register_wires_hooks_and_command():
    import fluent

    ctx = FakeCtx()
    fluent.register(ctx)
    assert "fluent" in ctx.commands
    assert set(ctx.hooks) == {"pre_tool_call", "post_tool_call", "transform_terminal_output"}


def test_adopt_shows_live_message_and_returns_nothing(tmp_store, monkeypatch):
    def fake_adopt(program, progress=None):
        progress("start", {"version": "1.0"})
        progress("subcommands", {"done": 2, "total": 2})
        progress("done", {})
        return make_card(program)

    monkeypatch.setattr(commands, "adopt", fake_adopt)
    ctx = FakeCtx(live=True)
    out = commands.handle(ctx, "adopt tool")
    assert out is None
    assert ctx.log[0][0] == "post"
    assert "Learning tool" in ctx.log[0][1]
    assert "is fluent" in ctx.log[-1][1]
    assert tmp_store.load("tool") is not None


def test_adopt_without_live_messages_replies_normally(tmp_store, monkeypatch):
    monkeypatch.setattr(commands, "adopt", lambda program, progress=None: make_card(program))
    out = commands.handle(FakeCtx(live=False), "adopt tool")
    assert "✅ tool 1.0 is fluent" in out
    assert "🔴 1 destroy" in out


def test_adopt_error_is_friendly(tmp_store):
    out = commands.handle(FakeCtx(live=False), "adopt definitely-not-a-program-xyz")
    assert out.startswith("⚠️") and "can't find" in out
    assert tmp_store.programs() == []


def test_show_forget_undo(tmp_store):
    tmp_store.save(make_card())
    ctx = FakeCtx(live=False)
    assert "tool 1.0 · fluent ✅" in commands.handle(ctx, "show tool")
    node = commands.handle(ctx, "show tool rm")
    assert node.startswith("🔴 tool rm") and "risky options: --force" in node
    assert "isn't in its help" in commands.handle(ctx, "show tool nope")
    assert "Forgot tool" in commands.handle(ctx, "forget tool")
    assert "is back" in commands.handle(ctx, "undo")
    assert "Fluent in 1 program" in commands.handle(ctx, "")


def test_unknown_verb_and_help(tmp_store):
    ctx = FakeCtx(live=False)
    assert "I don't know 'dance'" in commands.handle(ctx, "dance")
    assert "/fluent adopt" in commands.handle(ctx, "help")
    assert "Start with: /fluent adopt git" in commands.handle(ctx, "")
