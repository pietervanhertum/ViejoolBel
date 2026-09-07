"""Command-line entry point: ``viejoolbel run`` (and ``--help``)."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from . import __version__
from .config import get_settings
from .service import Service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viejoolbel", description="School bell system")
    parser.add_argument("--version", action="version", version=f"viejoolbel {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run the bell service and web interface")
    run.add_argument("--host", default=None)
    run.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.command in (None, "run"):
        settings = get_settings()
        service = Service(settings)
        service.start()
        app = service.build_app()
        try:
            uvicorn.run(
                app,
                host=args.host or settings.host,
                port=args.port or settings.port,
                log_level="info",
            )
        finally:
            service.stop()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
