from agent_framework import Executor, WorkflowContext, handler

from obungi_chat_agents_system.schemas import TicketCategory, TicketContext, TicketResponse


class ResponseFormatterExecutor(Executor):
    """Produces the final user-facing answer."""

    def __init__(self, id: str = "response_formatter") -> None:
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        metadata = {
            "category": context.category.value if context.category else None,
            "summary": context.summary,
            "dispatch_payload": context.dispatch_payload,
        }

        if context.category == TicketCategory.OTHER:
            await ctx.yield_output(
                TicketResponse(
                    status="unsupported",
                    message="Leider kann dieses System bei dieser Anfrage nicht helfen.",
                    metadata=metadata,
                )
            )
            return

        if not context.response:
            context.response = (
                "Deine Anfrage wurde aufgenommen. Wir melden uns so schnell wie möglich."
            )

        await ctx.yield_output(
            TicketResponse(
                status="completed",
                message=context.response,
                payload=context.dispatch_payload,
                metadata=metadata,
            )
        )

