import json
import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketContext, TicketResponse

IDENTITY_PROMPT = """Du bist ein Assistent, der Kontaktdaten aus Text extrahiert.
Analysiere die Anfrage und gib ein JSON mit genau diesen Feldern zurück:
{
  "name": "<Nachname oder voller Nachname>",
  "vorname": "<Vorname>",
  "email": "<E-Mail-Adresse>"
}
Lass Felder leer, wenn sie nicht eindeutig genannt werden. Verwende keine Erklärungen.
"""


class IdentityExtractorExecutor(Executor):
    """LLM-backed extractor that pulls name/vorname/email from the original text."""

    _EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
    _NAME_HINTS = {
        "name": re.compile(r"\b(?:name|familienname)\b[:\-]?\s*(?P<value>[A-Za-zÄÖÜäöüß\s'-]+)", re.IGNORECASE),
        "vorname": re.compile(r"\bvorname\b[:\-]?\s*(?P<value>[A-Za-zÄÖÜäöüß\s'-]+)", re.IGNORECASE),
    }

    def __init__(self, chat_client: AzureOpenAIChatClient, id: str = "identity") -> None:
        self.agent = chat_client.create_agent(instructions=IDENTITY_PROMPT, name=id)
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        missing = [field for field in ("name", "vorname", "email") if not getattr(context, field)]
        if not missing:
            await ctx.send_message(context)
            return

        response = await self.agent.run(context.original_message)
        parsed = self._parse_response(response.text)

        for field in missing:
            value = parsed.get(field)
            normalized = self._normalize_value(field, value)
            if normalized:
                setattr(context, field, normalized)

        still_missing = [field for field in ("name", "vorname", "email") if not getattr(context, field)]
        if still_missing:
            self._apply_regex_fallback(context, still_missing)

        await ctx.send_message(context)

    def _parse_response(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                fragment = text[start : end + 1]
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    return {}
        return {}

    def _normalize_value(self, field: str, value: Any) -> str | None:
        if not value:
            return None
        value = str(value).strip()
        if not value:
            return None
        if field == "email":
            match = self._EMAIL_PATTERN.search(value)
            return match.group(0).lower() if match else None
        return value

    def _apply_regex_fallback(self, context: TicketContext, missing: list[str]) -> None:
        text = context.original_message
        if "email" in missing and not context.email:
            if match := self._EMAIL_PATTERN.search(text):
                context.email = match.group(0).lower()

        for field in ("name", "vorname"):
            if field in missing and not getattr(context, field):
                pattern = self._NAME_HINTS.get(field)
                if pattern and (match := pattern.search(text)):
                    value = match.group("value").strip()
                    setattr(context, field, value or None)

