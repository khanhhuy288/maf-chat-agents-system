from __future__ import annotations

import asyncio
from typing import Any

from agent_framework import AgentExecutor, ChatAgent, Workflow, WorkflowBuilder
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.agents import (
    ClassificationExecutor,
    DispatcherExecutor,
    HistorianExecutor,
    IdentityExtractorExecutor,
    IntakeExecutor,
    ResponseFormatterExecutor,
    ValidationExecutor,
)
from obungi_chat_agents_system.config import settings
from obungi_chat_agents_system.schemas import TicketInput, TicketResponse


def create_chat_client() -> AzureOpenAIChatClient:
    return AzureOpenAIChatClient(
        api_key=settings.azure_openai_api_key,
        endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        deployment_name=settings.azure_openai_deployment,
    )


async def _run_workflow_helper(workflow: Workflow, ticket_input: TicketInput) -> TicketResponse | None:
    """Helper function to run the workflow asynchronously."""
    events = await workflow.run(ticket_input)
    outputs = events.get_outputs()
    return outputs[-1] if outputs else None


def create_conversational_agent(*, simulate_dispatch: bool = True) -> ChatAgent:
    """Create a standalone conversational agent for DevUI interaction.
    
    This agent provides a friendly conversational interface for users to interact with
    the ticket system. It integrates with the ticket workflow to process requests.
    """
    chat_client = create_chat_client()
    workflow = create_ticket_workflow(simulate_dispatch=simulate_dispatch)
    
    # Create a function tool that processes tickets through the workflow
    # Note: This function must be synchronous, so we use asyncio.run to execute the async workflow
    def process_ticket(
        message: str,
    ) -> dict[str, Any]:
        """Verarbeitet eine Ticket-Anfrage durch das Workflow-System.
        
        Das Workflow-System extrahiert automatisch Identitätsinformationen (Name, Vorname, E-Mail)
        aus der Nachricht. Du musst diese nicht selbst extrahieren.
        
        Args:
            message: Die vollständige Benutzeranfrage oder Nachricht (inklusive aller Identitätsinformationen)
        
        Returns:
            Ein Dictionary mit Status, Nachricht und Metadaten der Verarbeitung:
            - status: 'missing_identity', 'unsupported', 'completed', oder 'error'
            - message: Die Antwortnachricht vom Workflow
            - is_historian_answer: (Optional) True wenn die 'message' die direkte Historian-Antwort ist
            - direct_answer: (Optional) Die direkte Antwort vom Historian (falls is_historian_answer=True)
            - metadata: Zusätzliche Metadaten mit folgenden Feldern:
              * category: Die Kategorie der Anfrage ('Frage zur Historie von AI', 'O365 Frage', etc.)
              * missing_fields: Liste fehlender Felder (wenn status='missing_identity')
              * missing_labels: Labels für fehlende Felder (wenn status='missing_identity')
            - payload: Optional versendetes Payload (wenn Ticket erstellt wurde)
            
        WICHTIGE REGEL FÜR AI-HISTORIE-FRAGEN:
        Wenn 'is_historian_answer' = True ODER 'metadata.category' = 'Frage zur Historie von AI':
        - Die 'message' (oder 'direct_answer') ist die KOMPLETTE Antwort vom Historian-Executor
        - Diese Antwort muss EXAKT so an den Benutzer weitergegeben werden, OHNE Änderungen
        - Füge KEINE zusätzlichen Texte hinzu wie 'Ihr Ticket wurde erfolgreich...'
        - Die Antwort ist bereits vollständig und beantwortet die Frage des Benutzers
        """
        # Pass only the message - let the workflow's IdentityExtractorExecutor handle extraction
        ticket_input = TicketInput(message=message)
        
        try:
            # Run the async workflow in a new event loop or use the existing one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're already in an async context, we need to handle this differently
                    # For now, create a new event loop in a thread
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, _run_workflow_helper(workflow, ticket_input))
                        result = future.result()
                else:
                    result = loop.run_until_complete(_run_workflow_helper(workflow, ticket_input))
            except RuntimeError:
                # No event loop exists, create a new one
                result = asyncio.run(_run_workflow_helper(workflow, ticket_input))
            
            if not result:
                return {
                    "status": "error",
                    "message": "Es konnte keine Antwort generiert werden.",
                    "metadata": {},
                }
            
            # Build response with explicit category information
            metadata = result.metadata or {}
            category = metadata.get("category", "")
            
            # For AI history questions, the message IS the answer from HistorianExecutor
            # Make this explicit in the response
            response = {
                "status": result.status,
                "message": result.message,
                "metadata": metadata,
                "payload": result.payload,
            }
            
            # Add explicit flag for AI history to make it crystal clear
            if category == "Frage zur Historie von AI" and result.status == "completed":
                response["is_historian_answer"] = True
                response["direct_answer"] = result.message  # This is the answer to return directly
            
            return response
        except Exception as e:
            return {
                "status": "error",
                "message": f"Fehler bei der Verarbeitung: {str(e)}",
            }
    
    return chat_client.create_agent(
        name="Ticket Support Agent",
        instructions=(
            "Du bist ein freundlicher IT-Support-Assistent für das Obungi Ticket-System. "
            "Du hilfst Benutzern bei IT-Anfragen und verarbeitest diese durch ein internes Workflow-System.\n\n"
            "WICHTIGE VERHALTENSREGELN:\n\n"
            "1. **Anfragen verarbeiten:**\n"
            "   - Wenn der Benutzer eine konkrete Anfrage stellt, verwende IMMER die Funktion 'process_ticket'\n"
            "   - Übergebe NUR die vollständige Nachricht des Benutzers im 'message' Parameter\n"
            "   - Extrahiere NICHT selbst Identitätsinformationen - das Workflow-System macht das automatisch\n"
            "   - Die Funktion verarbeitet die Anfrage durch das Workflow-System, das automatisch Name, Vorname und E-Mail extrahiert\n\n"
            "2. **Antworten basierend auf Workflow-Ergebnis - KRITISCH:**\n"
            "   Nach jedem 'process_ticket' Aufruf MUSS du zuerst prüfen:\n"
            "   - Wenn 'is_historian_answer' = True ODER ('status' = 'completed' UND 'metadata.category' = 'Frage zur Historie von AI'):\n"
            "     * Die 'message' (oder 'direct_answer' falls vorhanden) ist die DIREKTE Antwort vom Historian-Executor\n"
            "     * Du MUSST diese Antwort EXAKT so an den Benutzer weitergeben, ohne Änderungen\n"
            "     * Füge KEINE zusätzlichen Texte hinzu wie 'Ihr Ticket wurde...' oder 'Ihr Ticket wurde erfolgreich...'\n"
            "     * Die Antwort enthält bereits die vollständige Antwort auf die AI-Historie-Frage\n"
            "     * Kopiere die Antwort 1:1 - keine Umformulierung, keine Ergänzungen\n"
            "     * Beispiel: Wenn message='Die Entwicklung von Chatbots begann mit ELIZA...', dann antworte genau mit diesem Text\n\n"
            "   - Wenn 'status' = 'completed' UND 'metadata.category' != 'Frage zur Historie von AI':\n"
            "     * Antworte: 'Ihr Ticket wurde erfolgreich an das IT-Team übergeben. Sie erhalten eine Rückmeldung per E-Mail.'\n\n"
            "   - Wenn 'status' = 'missing_identity':\n"
            "     * Frage höflich nach den fehlenden Feldern (siehe 'metadata.missing_fields')\n"
            "     * Verwende die Labels aus 'metadata.missing_labels' für die Frage\n"
            "     * Beispiel: 'Bitte geben Sie noch Ihre E-Mail-Adresse an.'\n"
            "     * Wenn der Benutzer die fehlenden Informationen liefert, rufe 'process_ticket' erneut mit der vollständigen Nachricht auf\n\n"
            "   - Wenn 'status' = 'unsupported':\n"
            "     * Sage höflich: 'Leider kann ich bei dieser Anfrage nicht helfen.'\n\n"
            "   - Wenn 'status' = 'error':\n"
            "     * Entschuldige dich: 'Es ist ein Fehler aufgetreten. Bitte versuchen Sie es erneut.'\n\n"
            "3. **Ton und Stil:**\n"
            "   - Sei immer freundlich und professionell\n"
            "   - Antworte auf Deutsch\n"
            "   - Verwende eine natürliche, gesprächige Sprache\n"
            "   - Wenn du nach Informationen fragst, sei spezifisch und verwende die exakten Feldnamen aus metadata\n\n"
            "4. **Workflow-Integration:**\n"
            "   - Nutze IMMER die 'process_ticket' Funktion für alle Anfragen\n"
            "   - Übergebe immer die vollständige Benutzernachricht - das Workflow-System extrahiert automatisch alle benötigten Informationen\n"
            "   - Wenn Identitätsinformationen fehlen, sammle sie im Gespräch und rufe dann 'process_ticket' erneut mit der vollständigen Nachricht auf\n\n"
            "5. **ENTSCHEIDUNGSBAUM nach process_ticket Aufruf:**\n"
            "   Schritt 1: Prüfe 'is_historian_answer' oder 'metadata.category'\n"
            "   Schritt 2a: Wenn 'is_historian_answer' = True ODER 'metadata.category' = 'Frage zur Historie von AI':\n"
            "              → Verwende 'direct_answer' (falls vorhanden) oder 'message' EXAKT so\n"
            "              → Keine zusätzlichen Texte, keine Umformulierung\n"
            "   Schritt 2b: Wenn 'status' = 'completed' UND category != 'Frage zur Historie von AI':\n"
            "              → Antworte: 'Ihr Ticket wurde erfolgreich an das IT-Team übergeben. Sie erhalten eine Rückmeldung per E-Mail.'\n"
            "   Schritt 2c: Wenn 'status' = 'missing_identity':\n"
            "              → Frage nach fehlenden Feldern\n"
            "   Schritt 2d: Wenn 'status' = 'unsupported':\n"
            "              → Sage: 'Leider kann ich bei dieser Anfrage nicht helfen.'\n"
            "   Schritt 2e: Wenn 'status' = 'error':\n"
            "              → Entschuldige dich und bitte um Wiederholung\n\n"
            "Beispiel-Ablauf für AI-Historie-Frage:\n"
            "1. Benutzer: 'Hi, mein Name ist Peter Schneider, meine E-Mail ist peter@example.com. Ich recherchiere die Entwicklung von Chatbots...'\n"
            "2. Du: Rufe 'process_ticket' auf mit der vollständigen Nachricht\n"
            "3. Workflow extrahiert automatisch: name='Schneider', vorname='Peter', email='peter@example.com'\n"
            "4. Workflow klassifiziert als 'Frage zur Historie von AI' und Historian generiert eine Antwort\n"
            "5. Funktion gibt zurück: status='completed', metadata.category='Frage zur Historie von AI', message='[Historian-Antwort]'\n"
            "6. Du: Prüfe metadata.category - es ist 'Frage zur Historie von AI'\n"
            "7. Du: Gib die 'message' EXAKT so weiter: '[Historian-Antwort]' (ohne zusätzliche Texte)\n\n"
            "Beispiel-Ablauf für andere Kategorien:\n"
            "1. Benutzer: 'Ich habe ein Problem mit meinem Login'\n"
            "2. Du: Rufe 'process_ticket' auf\n"
            "3. Workflow klassifiziert als 'Probleme bei der Anmeldung'\n"
            "4. Funktion gibt zurück: status='completed', metadata.category='Probleme bei der Anmeldung'\n"
            "5. Du: Prüfe metadata.category - es ist NICHT 'Frage zur Historie von AI'\n"
            "6. Du: Antworte: 'Ihr Ticket wurde erfolgreich an das IT-Team übergeben. Sie erhalten eine Rückmeldung per E-Mail.'"
        ),
        tools=[process_ticket],
    )


def create_ticket_workflow(*, simulate_dispatch: bool = True) -> Workflow:
    chat_client = create_chat_client()

    intake = IntakeExecutor()
    identity = IdentityExtractorExecutor(chat_client)
    validation = ValidationExecutor()
    classification = ClassificationExecutor(chat_client)
    historian = HistorianExecutor(chat_client)
    dispatcher = DispatcherExecutor(
        settings.ticket_logic_app_url, simulate_only=simulate_dispatch
    )
    formatter = ResponseFormatterExecutor()

    workflow = (
        WorkflowBuilder(
            name="Ticket Workflow",
            description="Sequential intake, classification, historian, dispatcher and formatter pipeline.",
        )
        .set_start_executor(intake)
        .add_edge(intake, identity)
        .add_edge(identity, validation)
        .add_edge(validation, classification)
        .add_edge(classification, historian)
        .add_edge(historian, dispatcher)
        .add_edge(dispatcher, formatter)
        .build()
    )

    return workflow


def create_conversational_workflow(*, simulate_dispatch: bool = True) -> Workflow:  # noqa: ARG001
    """Create a workflow that starts with a conversational agent.
    
    This version adds a conversational front-end agent that handles user interaction
    before the ticket processing workflow begins.
    
    Note: This workflow variant is not currently used but is available for future use.
    The conversational agent is served separately in DevUI for direct interaction.
    """
    # This workflow variant would require a custom executor to convert agent output
    # to TicketInput. For now, we serve the agent separately.
    # If needed in the future, we can implement a proper converter executor.
    raise NotImplementedError(
        "Conversational workflow integration requires additional implementation. "
        "Use the standalone conversational agent in DevUI instead."
    )

