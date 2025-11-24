from agent_framework import Executor, WorkflowContext, handler

from chat_agents_system.schemas import TicketContext, TicketResponse


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
        """Validate that all required identity fields are present.
        
        This executor implements a human-in-the-loop pattern: if identity fields are missing,
        it yields a response asking the user to provide them, and the workflow stops until
        the user provides the information in a follow-up message.
        """
        missing_attrs = [attr for attr in self.REQUIRED_FIELDS if not getattr(context, attr)]

        if missing_attrs:
            # Always ask for all three fields if any are missing
            # Use the exact format that IdentityExtractorExecutor expects: "Name, Vorname, E-Mail-Adresse"
            all_labels = list(self.REQUIRED_FIELDS.values())
            await ctx.yield_output(
                TicketResponse(
                    status="missing_identity",
                    message=(
                        "Bitte geben Sie Ihre Angaben im Format Name, Vorname, E-Mail-Adresse an. "
                        "Beispiel: Müller, Hans, hans@example.com"
                    ),
                    metadata={
                        "missing_fields": list(self.REQUIRED_FIELDS.keys()),
                        "missing_labels": all_labels,
                    },
                )
            )
            return

        await ctx.send_message(context)

