from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketCategory, TicketContext, TicketResponse

HISTORIAN_PROMPT = (
    "Du bist ein freundlicher Support-Agent. Beantworte Fragen zur Geschichte der KI in einfacher, "
    "leicht verständlicher Sprache auf Deutsch."
)


class HistorianExecutor(Executor):
    """Provides direct answers for AI history questions."""

    def __init__(self, chat_client: AzureOpenAIChatClient, id: str = "historian") -> None:
        self.agent = chat_client.create_agent(instructions=HISTORIAN_PROMPT, name=id)
        super().__init__(id=id)

    @handler
    async def handle(
        self, context: TicketContext, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        if context.category != TicketCategory.AI_HISTORY:
            await ctx.send_message(context)
            return

        prompt = context.cleaned_request or context.original_message
        # Use run() - response.text already aggregates all text content from the stream
        # The conversational agent in DevUI will handle streaming when it generates its response
        response = await self.agent.run(prompt)
        # response.text contains the complete aggregated text from all streaming updates
        context.response = response.text.strip() if response.text else ""

        await ctx.send_message(context)

