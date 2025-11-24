"""Production API server entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

import uvicorn

from chat_agents_system.api.main import create_app

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Start the Chat Agents System production API server."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host interface to bind. Defaults to {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on. Defaults to {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes. Defaults to 1. Use 4+ for production.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development (not recommended for production).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level. Defaults to INFO.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Main entry point for the API server."""
    args = parse_args(argv)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting Chat Agents System API on {args.host}:{args.port}")
    
    # Create FastAPI app
    app = create_app()
    
    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=args.workers if not args.reload else 1,  # Reload doesn't work with multiple workers
        reload=args.reload,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main(sys.argv[1:])

