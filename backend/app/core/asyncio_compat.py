"""Asyncio entry-point helpers for cross-platform database clients."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def selector_event_loop_factory() -> asyncio.AbstractEventLoop:
    """Create the event loop required by psycopg async connections on Windows."""

    return asyncio.SelectorEventLoop()


def run_async(coroutine: Coroutine[Any, Any, _T]) -> _T:
    """Run a top-level coroutine with a psycopg-compatible Windows loop."""

    if sys.platform == "win32":
        return asyncio.run(coroutine, loop_factory=selector_event_loop_factory)
    return asyncio.run(coroutine)
