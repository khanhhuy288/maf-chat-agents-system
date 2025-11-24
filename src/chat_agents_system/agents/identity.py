import re
from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from chat_agents_system.schemas import TicketContext, TicketInput, TicketResponse
from chat_agents_system.utils import get_logger, parse_json_response

# Pattern to match the required identity format: "Name, Vorname, E-Mail-Adresse"
# Must match the pattern in workflow.py
IDENTITY_FORMAT_PATTERN = re.compile(
    r"^[^,]+,\s*[^,]+,\s*[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.IGNORECASE
)

# Simple prompt for LLM extraction
IDENTITY_PROMPT = """Du bist ein Assistent, der Kontaktdaten aus Text extrahiert.

Extrahiere Name (Nachname), Vorname und E-Mail-Adresse aus dem gegebenen Text.

Gib ein JSON mit genau diesen Feldern zurück:
{
  "name": "<Nachname>",
  "vorname": "<Vorname>",
  "email": "<E-Mail-Adresse>"
}

Regeln:
- Wenn ein Feld nicht eindeutig identifiziert werden kann, lasse es leer (null oder leerer String)
- Verwende keine Erklärungen, nur das JSON
- Bei komma-getrennten Formaten: "Name, Vorname, E-Mail" → name=Name, vorname=Vorname, email=E-Mail
- Bei natürlicher Sprache: Extrahiere die Informationen so gut wie möglich
"""


class IdentityExtractorExecutor(Executor):
    """Simple LLM-backed extractor that pulls name/vorname/email from text.
    
    Uses a simple LLM prompt to extract identity information. If extraction fails
    or is incomplete, validation will prompt the user for the specific format.
    """

    _EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

    def __init__(self, chat_client: AzureOpenAIChatClient, id: str = "identity") -> None:
        self.agent = chat_client.create_agent(instructions=IDENTITY_PROMPT, name=id)
        super().__init__(id=id)

    @handler
    async def handle(
        self, ticket_input: TicketInput, ctx: WorkflowContext[TicketContext, TicketResponse]
    ) -> None:
        """Extract identity information (name, vorname, email) from the message.
        
        Simple approach:
        1. If original_message is provided, we're in follow-up mode - check strict format
        2. Use LLM to extract identity from the message
        3. Set original_message in context (from ticket_input or use message)
        4. If extraction fails or is incomplete, pass through to validation
        """
        logger = get_logger(__name__)
        message = ticket_input.message.strip()
        
        # If original_message is provided, we're processing a follow-up identity message
        # In this case, ONLY accept strict format "Name, Vorname, E-Mail-Adresse"
        # This ensures we don't process new queries when waiting for identity
        if ticket_input.original_message:
            if not IDENTITY_FORMAT_PATTERN.match(message):
                logger.warning(
                    f"IdentityExtractorExecutor - REJECTING: Follow-up doesn't match strict format: {repr(message[:100])}"
                )
                # Don't extract - pass through with original_message so validation will ask again
                # This prevents the workflow from processing the message as a new query
                context = TicketContext(
                    original_message=ticket_input.original_message,
                    name=ticket_input.name,
                    vorname=ticket_input.vorname,
                    email=ticket_input.email,
                )
                await ctx.send_message(context)
                return
        
        # Create initial context
        # Use original_message from ticket_input if provided, otherwise use message
        context = TicketContext(
            original_message=ticket_input.original_message or message,
            name=ticket_input.name,
            vorname=ticket_input.vorname,
            email=ticket_input.email,
        )
        
        # If all fields already provided, pass through
        if context.name and context.vorname and context.email:
            logger.debug("IdentityExtractorExecutor - all fields already provided")
            await ctx.send_message(context)
            return
        
        # Use LLM to extract identity information from the message
        try:
            logger.debug(f"IdentityExtractorExecutor - using LLM to extract from: {repr(message[:100])}")
            response = await self.agent.run(f"Extrahiere Name, Vorname und E-Mail aus folgendem Text:\n\n{message}")
            parsed = parse_json_response(response.text)
            logger.debug(f"IdentityExtractorExecutor - LLM parsed: {parsed}")
            
            # Update context with extracted values
            if not context.name and parsed.get("name"):
                context.name = str(parsed["name"]).strip() or None
            if not context.vorname and parsed.get("vorname"):
                context.vorname = str(parsed["vorname"]).strip() or None
            if not context.email and parsed.get("email"):
                email_value = str(parsed["email"]).strip()
                # Validate email format
                email_match = self._EMAIL_PATTERN.search(email_value)
                if email_match:
                    context.email = email_match.group(0).lower()
                else:
                    context.email = None
                    logger.warning(f"IdentityExtractorExecutor - invalid email format: {email_value}")
                    
        except Exception as e:
            logger.warning(f"IdentityExtractorExecutor - LLM extraction failed: {e}")
            # Continue with what we have (may be empty, validation will handle it)
        
        logger.debug(
            f"IdentityExtractorExecutor - final: name={context.name}, "
            f"vorname={context.vorname}, email={context.email}, "
            f"original_message={repr(context.original_message[:50])}"
        )
        
        await ctx.send_message(context)
