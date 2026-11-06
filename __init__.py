"""fluent: the LSP for your agent's terminal.

Hermes already checks the code it writes. fluent checks the shell commands it runs,
against the real help of the programs installed on this machine.

This module only wires the plugin into Hermes. The logic lives in ``core`` (pure
standard library, no Hermes imports) and the Hermes glue lives in ``glue``.
"""

from __future__ import annotations


def register(ctx):
    """Entry point Hermes calls when the plugin loads."""
    from .glue import hooks

    hooks.install(ctx)
