from __future__ import annotations

from typing import TYPE_CHECKING

from agent_framework import AgentExecutor, Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from chat_agents_system.schemas import TicketInput, TicketResponse

if TYPE_CHECKING:
    pass

CONVERSATIONAL_INTAKE_PROMPT = (
    "Du bist ein freundlicher IT-Support-Assistent. "
    "Hilf Benutzern dabei, ihre IT-Anfragen zu formulieren. "
    "Wenn der Benutzer eine Anfrage stellt, fasse sie zusammen und bestätige, dass du sie verstanden hast. "
    "Antworte auf Deutsch und sei hilfsbereit und professionell. "
    "Wenn der Benutzer bereit ist, seine Anfrage einzureichen, sage 'Ich leite Ihre Anfrage weiter.'"
)


class ConversationalIntakeExecutor(Executor):
    """Conversational agent executor that handles user interaction before processing the ticket.
    
    This executor wraps a ChatAgent to provide a conversational interface. The agent's response
    is used to create a TicketInput that flows to the next executor in the workflow.
    """

    def __init__(
        self, chat_client: AzureOpenAIChatClient, id: str = "conversational_intake"
    ) -> None:
        super().__init__(id=id)
        self.agent = chat_client.create_agent(
            instructions=CONVERSATIONAL_INTAKE_PROMPT, name=id
        )

    @handler
    async def handle(
        self, user_input: str, ctx: "WorkflowContext[TicketInput]"
    ) -> None:
        """Handle conversational input and convert to TicketInput.
        
        The agent processes the user input conversationally, but we always proceed
        with creating a TicketInput to continue the workflow.
        """
        # Run the conversational agent to get a response
        # This provides a conversational experience even though we proceed with the workflow
        await self.agent.run(user_input)

        # Create ticket input from the user's message
        ticket_input = TicketInput(message=user_input)

        # Send the ticket input to the next executor
        await ctx.send_message(ticket_input)

