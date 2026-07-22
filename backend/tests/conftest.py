"""Cross-platform pytest configuration."""

import asyncio
from collections.abc import Callable, Mapping

from pytest import Config, Item

from app.core.asyncio_compat import selector_event_loop_factory


def pytest_asyncio_loop_factories(
    config: Config,
    item: Item,
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Use the selector loop required by async psycopg, including on Windows."""

    del config, item
    return {"selector": selector_event_loop_factory}
