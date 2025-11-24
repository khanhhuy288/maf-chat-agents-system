from __future__ import annotations

import asyncio
from typing import Iterable

from rich.console import Console

from chat_agents_system.schemas import TicketInput
from chat_agents_system.workflow import create_ticket_workflow

console = Console()


CASES: dict[str, TicketInput] = {
    "ai_history": TicketInput(
        message=(
            "Ich bin Lena Schneider (lena.schneider@example.com) und möchte wissen, wie sich KI seit den 1950ern entwickelt hat."
        ),
    ),
    "sonstiges": TicketInput(
        name="Becker",
        vorname="Jonas",
        email="jonas.becker@example.com",
        message="Ich möchte wissen, ob ihr auch Firmenfeiern organisiert.",
    ),
    "o365": TicketInput(
        message="Hi, hier ist Anna Müller (anna.mueller@example.com). Bitte helft mir beim Freigeben einer SharePoint-Seite.",
    ),
    "hardware": TicketInput(
        message="Paul Maier bittet um ein neues Lenovo ThinkPad mit 32GB RAM. Kontakt: paul.maier@example.com.",
    ),
    "login": TicketInput(
        message="Laura Weber meldet, dass sie sich nicht mehr am VPN anmelden kann. Mail: laura.weber@example.com",
    ),
    "identity_loop": TicketInput(
        message="Ich brauche Hardware, bin aber nur als Max bekannt.",
    ),
}


async def run_case(case_id: str, ticket: TicketInput) -> None:
    workflow = create_ticket_workflow()
    result = await workflow.run(ticket)
    outputs = result.get_outputs()
    response = outputs[-1] if outputs else None

    console.rule(f"[bold blue]{case_id}")
    if response is None:
        console.print("[red]Keine Antwort erhalten.[/red]")
        return

    console.print(f"Status: {response.status}")
    console.print(f"Nachricht: {response.message}")
    if response.payload:
        console.print(f"Payload: {response.payload}")
    if response.metadata:
        console.print(f"Metadaten: {response.metadata}")


async def main(cases: Iterable[str] | None = None) -> None:
    target_cases = cases or CASES.keys()
    for case_id in target_cases:
        ticket = CASES[case_id]
        await run_case(case_id, ticket)


if __name__ == "__main__":
    asyncio.run(main())

