from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TicketCategory(str, Enum):
    AI_HISTORY = "Frage zur Historie von AI"
    O365 = "O365 Frage"
    HARDWARE = "Bestellung von Hardware"
    LOGIN = "Probleme bei der Anmeldung"
    OTHER = "Sonstiges"


@dataclass(slots=True)
class TicketInput:
    """Raw user input captured from CLI or DevUI."""

    message: str
    name: Optional[str] = None
    vorname: Optional[str] = None
    email: Optional[str] = None


@dataclass(slots=True)
class TicketContext:
    """Mutable state that flows through the workflow."""

    original_message: str
    name: Optional[str] = None
    vorname: Optional[str] = None
    email: Optional[str] = None
    category: Optional[TicketCategory] = None
    summary: Optional[str] = None
    cleaned_request: Optional[str] = None
    response: Optional[str] = None
    dispatch_payload: Optional[dict[str, Any]] = None


@dataclass(slots=True)
class TicketResponse:
    """Terminal response returned to the CLI or DevUI."""

    status: str
    message: str
    payload: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)

