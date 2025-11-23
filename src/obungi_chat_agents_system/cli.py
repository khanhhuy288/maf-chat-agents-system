from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from typing import Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status

from obungi_chat_agents_system.schemas import TicketInput, TicketResponse
from obungi_chat_agents_system.workflow import create_ticket_workflow

console = Console()
_composer_session = PromptSession()

STATUS_MESSAGES: Sequence[str] = (
    "[cyan]Schritt 1/5: Nachricht wird analysiert …[/cyan]",
    "[cyan]Schritt 2/5: Identität wird extrahiert …[/cyan]",
    "[cyan]Schritt 3/5: Angaben werden geprüft …[/cyan]",
    "[cyan]Schritt 4/5: Kategorie & Antwort werden ermittelt …[/cyan]",
    "[cyan]Schritt 5/5: Antwort wird formatiert …[/cyan]",
)
STATUS_INTERVAL_SECONDS = 1.8
COMPOSER_COMMANDS = {
    ":preview": "Aktuelle Nachricht anzeigen",
    ":clear": "Bisherige Eingabe löschen",
    ":help": "Liste aller Befehle anzeigen",
    ":quit": "Sitzung beenden (entspricht STRG+C)",
}


def _render_composer_help() -> None:
    lines = ["[bold]STRG+J[/bold] – Nachricht sofort senden (Shortcut)"]
    lines.extend(
        f"[bold]{cmd}[/bold] – {info}" for cmd, info in COMPOSER_COMMANDS.items()
    )
    lines.append("[bold]::[/bold] am Zeilenanfang, um ein führendes ':' als Text zu schreiben.")
    console.print(
        Panel(
            "\n".join(lines),
            title="Kommandos",
            border_style="cyan",
        )
    )


def _render_preview(lines: list[str]) -> None:
    if not lines:
        console.print("[dim]Noch keine Nachricht erfasst.[/dim]")
        return
    text = "\n".join(lines)
    char_count = sum(len(line) for line in lines)
    console.print(
        Panel(
            text,
            title=f"Vorschau · {len(lines)} Zeilen · {char_count} Zeichen",
            border_style="green",
        )
    )


def _prompt_composer_line() -> tuple[str, bool]:
    shortcut = {"value": False}
    bindings = KeyBindings()

    def _register(binding: str) -> None:
        @bindings.add(binding)
        def _(event) -> None:
            shortcut["value"] = True
            event.app.exit(event.app.current_buffer.text)

    _register("c-j")

    line = _composer_session.prompt("│ ", key_bindings=bindings)
    return line, shortcut["value"]


def collect_ticket_message() -> str:
    console.print(
        Panel(
            "Schreibe deine Anfrage frei heraus. Leerzeilen sind erlaubt.\n"
            "Drücke [bold]STRG+J[/bold], wenn du fertig bist, oder tippe [bold]:help[/bold] für alle Befehle.",
            title="Ticket Composer",
            border_style="cyan",
        )
    )
    lines: list[str] = []
    while True:
        try:
            line, shortcut_sent = _prompt_composer_line()
        except EOFError:
            raise KeyboardInterrupt

        if line.startswith("::"):
            lines.append(line[1:])
            continue

        stripped = line.strip()

        if shortcut_sent and not stripped.startswith(":"):
            if line:
                lines.append(line)
            message = "\n".join(lines).strip()
            if not message:
                console.print("[yellow]Es wurde noch kein Text eingegeben.[/yellow]")
                continue
            return message

        if stripped.startswith(":"):
            command = stripped.lower()
            if command == ":preview":
                _render_preview(lines)
                continue
            if command == ":clear":
                lines.clear()
                console.print("[green]Nachricht gelöscht. Du kannst neu beginnen.[/green]")
                continue
            if command == ":help":
                _render_composer_help()
                continue
            if command == ":quit":
                raise KeyboardInterrupt
            console.print(f"[yellow]Unbekannter Befehl '{command}'. Tippe :help für Hilfe.[/yellow]")
            continue

        lines.append(line)


async def _cycle_status(status: Status, messages: Sequence[str]) -> None:
    idx = 0
    total = len(messages)
    while True:
        status.update(messages[idx % total])
        idx += 1
        await asyncio.sleep(STATUS_INTERVAL_SECONDS)


async def run_ticket_flow(
    ticket_input: TicketInput, *, simulate_dispatch: bool = True
) -> TicketResponse | None:
    workflow = create_ticket_workflow(simulate_dispatch=simulate_dispatch)
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI für das Ticket-Workflow-System."
    )
    parser.add_argument(
        "--enable-dispatch",
        action="store_true",
        help="HTTP-POSTs an die Logic App aktivieren (standardmäßig deaktiviert).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
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
                response = asyncio.run(
                    run_ticket_flow(
                        ticket_input, simulate_dispatch=not args.enable_dispatch
                    )
                )
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


