from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketCategory, TicketContext, TicketResponse
from obungi_chat_agents_system.utils import parse_json_response


CLASSIFICATION_PROMPT = """Du bist ein Service-Dispatcher. Analysiere die folgende Anfrage und ordne sie exakt einer der Kategorien zu:
- Frage zur Historie von AI
- O365 Frage
- Bestellung von Hardware
- Probleme bei der Anmeldung
- Sonstiges

Erstelle zusätzlich eine sehr kurze Zusammenfassung (weniger als 10 Wörter) sowie eine bereinigte Version der Anfrage ohne unnötige Grüße.

Gib deine Antwort ausschließlich als JSON mit folgendem Schema:
{{
  "category": "<Kategorie exakt wie oben>",
  "summary": "<max 9 Wörter>",
  "cleaned_request": "<bereinigter Klartext>"
}}
"""


class ClassificationExecutor(Executor):
    """LLM-backed node that categorizes and summarizes the ticket."""

    def __init__(self, chat_client: AzureOpenAIChatClient, id: str = "classification") -> None:
        self.agent = chat_client.create_agent(instructions=CLASSIFICATION_PROMPT, name=id)
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        payload = (
            f"Name: {context.name}\n"
            f"Vorname: {context.vorname}\n"
            f"E-Mail: {context.email}\n"
            f"Anfrage:\n{context.original_message}"
        )
        response = await self.agent.run(payload)
        parsed = parse_json_response(response.text)

        context.summary = parsed.get("summary") or "Ticket"
        context.summary = self._enforce_summary_limit(context.summary)
        context.cleaned_request = parsed.get("cleaned_request") or context.original_message
        context.category = self._map_category(parsed.get("category"))

        await ctx.send_message(context)

    @staticmethod
    def _enforce_summary_limit(summary: str) -> str:
        words = summary.split()
        if len(words) <= 9:
            return summary.strip()
        return " ".join(words[:9]).strip()

    @staticmethod
    def _map_category(raw: Any) -> TicketCategory:
        try:
            if raw:
                raw = str(raw).strip()
                for category in TicketCategory:
                    if category.value.lower() == raw.lower():
                        return category
        except Exception:
            pass
        return TicketCategory.OTHER

