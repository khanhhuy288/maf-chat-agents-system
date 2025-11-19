from agent_framework import Executor, WorkflowContext, handler

from obungi_chat_agents_system.schemas import TicketContext, TicketResponse


class ValidationExecutor(Executor):
    """Ensures mandatory identity attributes are captured before classification."""

    REQUIRED_FIELDS = {
        "name": "Name",
        "vorname": "Vorname",
        "email": "E-Mail-Adresse",
    }

    def __init__(self, id: str = "validation") -> None:
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        missing_attrs = [attr for attr in self.REQUIRED_FIELDS if not getattr(context, attr)]
        missing_labels = [self.REQUIRED_FIELDS[attr] for attr in missing_attrs]

        if missing_attrs:
            human_list = ", ".join(missing_labels)
            message = (
                "Bitte ergänzen Sie folgende Angaben, damit wir Ihr Ticket verarbeiten können: "
                f"{human_list}."
            )
            await ctx.yield_output(
                TicketResponse(
                    status="missing_identity",
                    message=message,
                    metadata={
                        "missing_fields": missing_attrs,
                        "missing_labels": missing_labels,
                    },
                )
            )
            return

        await ctx.send_message(context)

