import re

from agent_framework import Executor, WorkflowContext, handler

from chat_agents_system.schemas import TicketContext, TicketInput, TicketResponse


class IntakeExecutor(Executor):
    """Normalize raw user input into the workflow context."""

    _NAME_PATTERN = re.compile(r"\bname\s*[:\-]\s*(?P<value>[^,\n]+)", re.IGNORECASE)
    _VORNAME_PATTERN = re.compile(r"\bvorname\s*[:\-]\s*(?P<value>[^,\n]+)", re.IGNORECASE)
    _EMAIL_PATTERN = re.compile(r"\b(?:email|e-mail)\s*[:\-]\s*(?P<value>[^\s,;]+)", re.IGNORECASE)

    def __init__(self, id: str = "intake") -> None:
        super().__init__(id=id)

    @handler
    async def handle(
        self, ticket_input: TicketInput, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        message = ticket_input.message.strip()

        context = TicketContext(
            original_message=message,
            name=ticket_input.name or self._extract_value(self._NAME_PATTERN, message),
            vorname=ticket_input.vorname or self._extract_value(self._VORNAME_PATTERN, message),
            email=ticket_input.email or self._extract_value(self._EMAIL_PATTERN, message),
        )

        await ctx.send_message(context)

    @staticmethod
    def _extract_value(pattern: re.Pattern[str], text: str) -> str | None:
        if not text:
            return None
        if match := pattern.search(text):
            return match.group("value").strip()
        return None

