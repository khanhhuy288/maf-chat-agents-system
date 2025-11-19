from __future__ import annotations

import asyncio
import asyncio
from contextlib import suppress
from typing import Sequence

from rich.console import Console
from rich.prompt import Prompt
from rich.status import Status

from obungi_chat_agents_system.schemas import TicketInput, TicketResponse
from obungi_chat_agents_system.workflow import create_ticket_workflow

console = Console()

STATUS_MESSAGES: Sequence[str] = (
    "[cyan]Schritt 1/5: Nachricht wird analysiert …[/cyan]",
    "[cyan]Schritt 2/5: Identität wird extrahiert …[/cyan]",
    "[cyan]Schritt 3/5: Angaben werden geprüft …[/cyan]",
    "[cyan]Schritt 4/5: Kategorie & Antwort werden ermittelt …[/cyan]",
    "[cyan]Schritt 5/5: Antwort wird formatiert …[/cyan]",
)
STATUS_INTERVAL_SECONDS = 1.8


def collect_ticket_message() -> str:
    console.print(
        "[bold]Bitte beschreibe dein Anliegen (Leerzeile zum Abschluss, STRG+C zum Beenden).[/bold]"
    )
    lines: list[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            line = ""

        if not line.strip():
            if not lines:
                continue
            break

        lines.append(line)

    message = "\n".join(lines).strip()
    if not message:
        console.print("[red]Es wurde keine Nachricht eingegeben. Bitte erneut versuchen.[/red]")
        return collect_ticket_message()
    return message


async def _cycle_status(status: Status, messages: Sequence[str]) -> None:
    idx = 0
    total = len(messages)
    while True:
        status.update(messages[idx % total])
        idx += 1
        await asyncio.sleep(STATUS_INTERVAL_SECONDS)


async def run_ticket_flow(ticket_input: TicketInput) -> TicketResponse | None:
    workflow = create_ticket_workflow()
    with console.status(
        "[bold cyan]Workflow wird gestartet …[/bold cyan]", spinner="dots"
    ) as status:
        indicator = asyncio.create_task(_cycle_status(status, STATUS_MESSAGES))
        try:
            events = await workflow.run(ticket_input)
        finally:
            indicator.cancel()
            with suppress(asyncio.CancelledError):
                await indicator
            status.update("[bold green]Workflow abgeschlossen.[/bold green]")

    outputs = events.get_outputs()
    return outputs[-1] if outputs else None


def render_response(response: TicketResponse | None) -> None:
    if response is None:
        console.print("[red]Keine Antwort erhalten.[/red]")
        return

    console.print("\n[bold green]Antwort[/bold green]")
    console.print(response.message)
    if response.payload:
        console.print("\n[bold]Versandtes JSON:[/bold]")
        console.print(response.payload)
    if response.metadata:
        console.print("\n[bold]Metadaten:[/bold]")
        console.print({k: v for k, v in response.metadata.items() if v})


def prompt_missing_fields(missing_fields: list[str]) -> dict[str, str]:
    field_labels = {
        "name": "Nachname (z. B. 'Schneider')",
        "vorname": "Vorname",
        "email": "E-Mail-Adresse",
    }
    collected: dict[str, str] = {}
    for field in missing_fields:
        label = field_labels.get(field, field)
        while True:
            value = Prompt.ask(f"{label}").strip()
            if value:
                collected[field] = value
                break
            console.print("[yellow]Dieses Feld ist erforderlich.[/yellow]")
    return collected


def main() -> None:
    console.print("[dim]Zum Beenden jederzeit STRG+C drücken.[/dim]\n")
    while True:
        try:
            message = collect_ticket_message()
        except KeyboardInterrupt:
            console.print("\nAbgebrochen.")
            return

        known_fields: dict[str, str | None] = {
            "name": None,
            "vorname": None,
            "email": None,
        }

        while True:
            ticket_input = TicketInput(
                message=message,
                name=known_fields["name"],
                vorname=known_fields["vorname"],
                email=known_fields["email"],
            )
            try:
                response = asyncio.run(run_ticket_flow(ticket_input))
            except KeyboardInterrupt:
                console.print("\nAbgebrochen.")
                return

            if response is None:
                console.print(
                    "[red]Es wurde keine Antwort vom Workflow zurückgegeben.[/red]"
                )
                return

            if response.status == "missing_identity":
                console.print(f"\n[bold yellow]{response.message}[/bold yellow]")
                missing_fields = (
                    response.metadata.get("missing_fields", [])
                    if response.metadata
                    else []
                )
                if not missing_fields:
                    console.print(
                        "[red]Unbekannte fehlende Felder. Vorgang abgebrochen.[/red]"
                    )
                    return
                updates = prompt_missing_fields(missing_fields)
                for key, value in updates.items():
                    known_fields[key] = value
                console.print("[green]Danke! Ich versuche es erneut.[/green]\n")
                continue

            render_response(response)
            break


