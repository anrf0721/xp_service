"""Process entry. Ordinary start listens; --initialize creates tables and exits."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

logger = logging.getLogger("xp_procedure_service")

from xp_procedure_service.app.bootstrap import initialize
from xp_procedure_service.app.factory import create_app
from xp_procedure_service.common.errors import ConfigurationError
from xp_procedure_service.infrastructure.config import DEFAULT_PORT, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xp_procedure_service")
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="create tables and seed the placeholder procedure, then exit",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        if args.initialize:
            initialize(settings)
            return 0
        app = create_app(settings)
    except ConfigurationError:
        print("configuration error", file=sys.stderr)
        return 2
    except Exception as exc:
        logger.error("startup failed: %s", type(exc).__name__)
        print("startup failed", file=sys.stderr)
        return 1
    uvicorn.run(app, host=settings.bind_host, port=DEFAULT_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
