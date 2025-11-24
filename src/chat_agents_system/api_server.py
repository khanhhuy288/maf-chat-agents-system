"""Production API server entry point."""

from __future__ import annotations

import argparse
import logging
import socket
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


def is_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_free_port(host: str, start_port: int = 8000, max_attempts: int = 10) -> int | None:
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if is_port_available(host, port):
            return port
    return None


def main(argv: Sequence[str] | None = None) -> None:
    """Main entry point for the API server."""
    args = parse_args(argv)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    logger = logging.getLogger(__name__)
    
    # Check if port is available
    if not is_port_available(args.host, args.port):
        import subprocess
        import platform
        
        # Try to find what's using the port
        if platform.system() == "Darwin":  # macOS
            try:
                result = subprocess.run(
                    ["lsof", "-i", f":{args.port}"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                process_info = result.stdout.strip()
                if process_info:
                    logger.error(f"Port {args.port} is already in use:\n{process_info}")
                else:
                    logger.error(f"Port {args.port} is already in use.")
            except Exception:
                logger.error(f"Port {args.port} is already in use.")
        else:
            logger.error(f"Port {args.port} is already in use.")
        
        # Suggest alternatives
        free_port = find_free_port(args.host, args.port + 1)
        if free_port:
            logger.error(
                f"\n💡 Tip: Use a different port with --port {free_port}\n"
                f"   Example: uv run chat-agents-system-api --reload --port {free_port}"
            )
        else:
            logger.error(
                f"\n💡 Tip: Use a different port with --port <number>\n"
                f"   Example: uv run chat-agents-system-api --reload --port 8001"
            )
        
        sys.exit(1)
    
    logger.info(f"Starting Chat Agents System API on {args.host}:{args.port}")
    
    # For reload mode, uvicorn requires an import string, not an app object
    # This allows uvicorn to reload the module and recreate the app on file changes
    if args.reload:
        # Use import string format: "module.path:variable_name"
        app_str = "chat_agents_system.api.main:app"
        uvicorn.run(
            app_str,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level.lower(),
        )
    else:
        # For production (no reload), we can use the app object directly
        app = create_app()
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level=args.log_level.lower(),
        )


if __name__ == "__main__":
    main(sys.argv[1:])

