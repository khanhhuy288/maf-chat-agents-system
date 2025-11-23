from __future__ import annotations

import argparse
import logging
from typing import Sequence

from agent_framework.devui import serve

from obungi_chat_agents_system.workflow import (
    create_conversational_agent,
    create_ticket_workflow,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the Microsoft Agent Framework Dev UI for the ticket workflow."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on. Defaults to 8080.")
    parser.add_argument(
        "--mode",
        choices=("developer", "user"),
        default="developer",
        help="Dev UI mode. Developer mode keeps advanced controls enabled.",
    )
    parser.add_argument(
        "--auto-open",
        action="store_true",
        help="Automatically open the Dev UI in the default browser once the server is ready.",
    )
    parser.add_argument(
        "--cors-origin",
        dest="cors_origins",
        action="append",
        help="Allow an additional CORS origin. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--enable-dispatch",
        action="store_true",
        help=(
            "Enable HTTP calls to the Logic App dispatcher. "
            "By default, dispatch is simulated (no actual POST requests are sent)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level for the Dev UI launcher.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    simulate_dispatch = not args.enable_dispatch
    workflow = create_ticket_workflow(simulate_dispatch=simulate_dispatch)
    conversational_agent = create_conversational_agent(simulate_dispatch=simulate_dispatch)

    logging.info(
        "Launching Dev UI with workflow '%s' and conversational agent on %s:%s (simulate_dispatch=%s)",
        workflow.name or "Ticket Workflow",
        args.host,
        args.port,
        simulate_dispatch,
    )

    # Serve both the workflow and the conversational agent
    # The agent will appear in DevUI and can be interacted with conversationally
    serve(
        entities=[workflow, conversational_agent],
        host=args.host,
        port=args.port,
        auto_open=args.auto_open,
        cors_origins=args.cors_origins,
        mode=args.mode,
    )


if __name__ == "__main__":
    main()

