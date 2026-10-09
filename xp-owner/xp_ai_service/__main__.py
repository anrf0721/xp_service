"""Run the AI service or explicitly initialize its schema."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from xp_ai_service.app.settings import load_settings
from xp_ai_service.infrastructure.database import create_engine_from_url, initialize_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xp_ai_service")
    parser.add_argument(
        "--initialize",
        action="store_true",
        help="Create tables from models and exit. Startup never does this automatically.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    if args.initialize:
        engine = create_engine_from_url(settings.database_url)
        try:
            initialize_schema(engine)
        finally:
            engine.dispose()
        return
    uvicorn.run(
        "xp_ai_service.app.main:app",
        host=settings.bind_host,
        port=8002,
        factory=False,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("xp_ai_service failed to start", file=sys.stderr)
        raise SystemExit(1) from None
