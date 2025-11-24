import httpx

from agent_framework import Executor, WorkflowContext, handler

from chat_agents_system.schemas import TicketCategory, TicketContext, TicketResponse


class DispatcherExecutor(Executor):
    """Posts structured tickets to the Logic App endpoint."""

    _SUCCESS_MESSAGE = (
        "Das Ticket wurde erfolgreich an das IT-Team übergeben. "
        "Du erhältst eine Rückmeldung per E-Mail."
    )

    DISPATCHABLE = {
        TicketCategory.AI_HISTORY,
        TicketCategory.O365,
        TicketCategory.HARDWARE,
        TicketCategory.LOGIN,
    }

    def __init__(
        self, logic_app_url: str, id: str = "dispatcher", simulate_only: bool = True
    ) -> None:
        super().__init__(id=id)
        self.logic_app_url = logic_app_url
        self.simulate_only = simulate_only

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        if context.category not in self.DISPATCHABLE:
            await ctx.send_message(context)
            return

        payload = {
            "name": context.name,
            "vorname": context.vorname,
            "email": context.email,
            "kategorie": context.category.value if context.category else None,
            "zusammenfassung": context.summary,
            "anfrage": context.original_message,
        }

        if self.simulate_only:
            context.dispatch_payload = payload
            if not context.response:
                context.response = self._SUCCESS_MESSAGE
            await ctx.send_message(context)
            return

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(self.logic_app_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            await ctx.yield_output(
                TicketResponse(
                    status="dispatch_error",
                    message="Die Weiterleitung an das IT-Team ist fehlgeschlagen.",
                    metadata={"error": str(exc), "payload": payload},
                )
            )
            return

        context.dispatch_payload = payload
        if not context.response:
            context.response = self._SUCCESS_MESSAGE

        await ctx.send_message(context)

