"""Run Uvicorn with an event loop compatible with async psycopg on Windows."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.core.asyncio_compat import selector_event_loop_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loop = selector_event_loop_factory if sys.platform == "win32" else "auto"
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        loop=loop,
    )


if __name__ == "__main__":
    main()
