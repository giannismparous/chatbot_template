from __future__ import annotations

from packages.core.stack.factory import Stack, build_stack

_stack: Stack | None = None


def get_stack() -> Stack:
    global _stack
    if _stack is None:
        _stack = build_stack()
    return _stack


def reset_stack() -> None:
    global _stack
    _stack = None
