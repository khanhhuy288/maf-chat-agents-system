from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agent_framework import AgentExecutor, ChatAgent, WorkflowContext, handler
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.schemas import TicketInput, TicketResponse

if TYPE_CHECKING:
    from agent_framework import Workflow

CONVERSATIONAL_WORKFLOW_PROMPT = """Du bist ein freundlicher IT-Support-Assistent für das Obungi Ticket-System.

Deine Aufgabe ist es, Benutzern bei IT-Anfragen zu helfen. Du verarbeitest Anfragen durch ein internes Workflow-System.

WICHTIGE VERHALTENSREGELN:

1. **Identitätsinformationen sammeln:**
   - Wenn Name, Vorname oder E-Mail fehlen, frage höflich danach
   - Beispiel: "Bitte geben Sie noch Ihren Nachnamen an."
   - Warte auf die Antwort, bevor du fortfährst

2. **Anfragen verarbeiten:**
   - Wenn alle erforderlichen Informationen vorhanden sind, verarbeite die Anfrage
   - Fasse die Anfrage kurz zusammen, um zu bestätigen, dass du sie verstanden hast
   - Antworte dann basierend auf der Kategorie der Anfrage

3. **Antworten basierend auf Kategorie:**
   - **Frage zur Historie von AI**: Beantworte die Frage direkt in 2-3 Absätzen
   - **O365 Frage, Hardware, Login**: Bestätige, dass das Ticket erstellt wurde und eine E-Mail folgt
   - **Sonstiges**: Sage höflich, dass du bei dieser Anfrage nicht helfen kannst

4. **Ton und Stil:**
   - Sei immer freundlich und professionell
   - Antworte auf Deutsch
   - Verwende eine natürliche, gesprächige Sprache
   - Wenn du nach Informationen fragst, sei spezifisch (z.B. "Bitte geben Sie Ihre E-Mail-Adresse an")

5. **Workflow-Integration:**
   - Nutze das interne Workflow-System, um Anfragen zu verarbeiten
   - Wenn das Workflow-System fehlende Felder meldet, frage danach
   - Wenn das Workflow-System eine Antwort liefert, verwende diese

Denke daran: Du bist ein Assistent, der durch ein Workflow-System unterstützt wird. Nutze die Workflow-Ergebnisse, um angemessen zu antworten."""


class WorkflowConversationalExecutor(AgentExecutor):
    """Conversational agent that integrates with the ticket workflow.
    
    This executor wraps a ChatAgent and integrates it with the ticket workflow.
    It processes user input through the workflow and formats responses conversationally.
    """

    def __init__(
        self,
        chat_client: AzureOpenAIChatClient,
        workflow: "Workflow",
        id: str = "workflow_conversational",
    ) -> None:
        agent = chat_client.create_agent(
            instructions=CONVERSATIONAL_WORKFLOW_PROMPT,
            name=id,
        )
        super().__init__(agent=agent, id=id)
        self.workflow = workflow
        self._conversation_state: dict[str, dict[str, str | None]] = {}

    @handler
    async def handle(
        self, user_input: str, ctx: "WorkflowContext[str, str]"
    ) -> None:
        """Handle conversational input and process through workflow.
        
        This method:
        1. Extracts or retrieves identity information from conversation state
        2. Runs the workflow with the user input
        3. Checks workflow results for missing fields
        4. Formats appropriate conversational responses
        """
        # Get or initialize conversation state
        conversation_id = getattr(ctx, "conversation_id", "default")
        if conversation_id not in self._conversation_state:
            self._conversation_state[conversation_id] = {
                "name": None,
                "vorname": None,
                "email": None,
            }

        state = self._conversation_state[conversation_id]

        # Try to extract identity from current input
        self._extract_identity_from_input(user_input, state)

        # Create ticket input with known identity
        ticket_input = TicketInput(
            message=user_input,
            name=state["name"],
            vorname=state["vorname"],
            email=state["email"],
        )

        # Run the workflow
        try:
            events = await self.workflow.run(ticket_input)
            outputs = events.get_outputs()
            workflow_response: TicketResponse | None = outputs[-1] if outputs else None
        except Exception as e:
            await ctx.send_message(
                f"Es ist ein Fehler aufgetreten: {str(e)}. Bitte versuchen Sie es erneut."
            )
            return

        if not workflow_response:
            await ctx.send_message(
                "Es konnte keine Antwort generiert werden. Bitte versuchen Sie es erneut."
            )
            return

        # Handle missing identity fields
        if workflow_response.status == "missing_identity":
            missing_fields = (
                workflow_response.metadata.get("missing_fields", [])
                if workflow_response.metadata
                else []
            )
            if missing_fields:
                # Update state to track what we're asking for
                response_message = self._format_missing_fields_request(
                    missing_fields, workflow_response.message
                )
                await ctx.send_message(response_message)
                return

        # Handle unsupported requests
        if workflow_response.status == "unsupported":
            await ctx.send_message(workflow_response.message)
            return

        # Handle successful processing
        if workflow_response.status == "completed":
            # Update state with confirmed identity
            if workflow_response.metadata:
                if "name" in workflow_response.metadata:
                    state["name"] = workflow_response.metadata.get("name")
                if "vorname" in workflow_response.metadata:
                    state["vorname"] = workflow_response.metadata.get("vorname")
                if "email" in workflow_response.metadata:
                    state["email"] = workflow_response.metadata.get("email")

            # Format the response conversationally
            response_message = self._format_success_response(workflow_response)
            await ctx.send_message(response_message)
            return

        # Fallback
        await ctx.send_message(
            workflow_response.message or "Ihre Anfrage wurde verarbeitet."
        )

    def _extract_identity_from_input(self, text: str, state: dict[str, str | None]) -> None:
        """Try to extract identity information from user input using simple patterns."""
        import re

        # Email pattern
        email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
        if not state["email"]:
            if match := email_pattern.search(text):
                state["email"] = match.group(0).lower()

        # Name patterns
        name_patterns = {
            "name": re.compile(
                r"(?:name|nachname|familienname)\s*[:\-]?\s*([A-Za-zÄÖÜäöüß\s'-]+)",
                re.IGNORECASE,
            ),
            "vorname": re.compile(
                r"vorname\s*[:\-]?\s*([A-Za-zÄÖÜäöüß\s'-]+)", re.IGNORECASE
            ),
        }

        for field, pattern in name_patterns.items():
            if not state[field]:
                if match := pattern.search(text):
                    value = match.group(1).strip()
                    if value:
                        state[field] = value

    def _format_missing_fields_request(
        self, missing_fields: list[str], base_message: str
    ) -> str:
        """Format a conversational request for missing fields."""
        field_labels = {
            "name": "Ihren Nachnamen",
            "vorname": "Ihren Vornamen",
            "email": "Ihre E-Mail-Adresse",
        }

        if len(missing_fields) == 1:
            field = missing_fields[0]
            label = field_labels.get(field, field)
            return f"Bitte geben Sie noch {label} an, damit ich Ihre Anfrage verarbeiten kann."
        else:
            labels = [field_labels.get(f, f) for f in missing_fields]
            if len(labels) == 2:
                return f"Bitte geben Sie noch {labels[0]} und {labels[1]} an, damit ich Ihre Anfrage verarbeiten kann."
            else:
                last = labels[-1]
                others = ", ".join(labels[:-1])
                return f"Bitte geben Sie noch {others} und {last} an, damit ich Ihre Anfrage verarbeiten kann."

    def _format_success_response(self, response: TicketResponse) -> str:
        """Format a successful workflow response conversationally."""
        message = response.message or "Ihre Anfrage wurde verarbeitet."

        # If there's a dispatch payload, the ticket was sent
        if response.payload:
            # Check category from metadata
            category = (
                response.metadata.get("category") if response.metadata else None
            )
            if category == "Frage zur Historie von AI":
                # This is a direct answer, return it as-is
                return message
            else:
                # Ticket was created
                return (
                    f"{message}\n\n"
                    "Ihr Ticket wurde erfolgreich an das IT-Team übergeben. "
                    "Sie erhalten eine Rückmeldung per E-Mail."
                )

        return message

