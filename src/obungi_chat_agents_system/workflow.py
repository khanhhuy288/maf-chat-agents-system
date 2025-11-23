from __future__ import annotations

import asyncio
import hashlib
import re
import threading
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

# Thread-safe state tracking for identity requests
# Maps state_key (hash of original message or thread_id) -> {"waiting_for_identity": bool, "original_message": str | None}
_identity_state: dict[str, dict[str, Any]] = {}
_state_lock = threading.Lock()

# Pattern to match the required identity format: "Name, Vorname, E-Mail-Adresse"
_IDENTITY_FORMAT_PATTERN = re.compile(
    r"^[^,]+,\s*[^,]+,\s*[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.IGNORECASE
)


def _get_state_key(thread_id: str | None, message: str | None = None) -> str:
    """Generate a state key from thread_id or message hash."""
    if thread_id:
        return f"thread_{thread_id}"
    elif message:
        # Use hash of message as fallback
        message_hash = hashlib.md5(message.encode()).hexdigest()
        return f"msg_{message_hash}"
    else:
        return "default"


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
        original_message: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Verarbeitet eine Ticket-Anfrage durch das Workflow-System.
        
        Das Workflow-System extrahiert automatisch Identitätsinformationen (Name, Vorname, E-Mail)
        aus der Nachricht. Du musst diese nicht selbst extrahieren.
        
        Args:
            message: Die aktuelle Benutzeranfrage oder Nachricht.
                   Wenn 'original_message' angegeben ist, sollte 'message' die Identitätsinformationen enthalten
                   (z.B. "Tran, Huy, khanhhuy288@gmail.com").
                   Wenn 'original_message' None ist, sollte 'message' die vollständige Anfrage enthalten.
            original_message: (Optional) Die ursprüngliche Anfrage, für die Identitätsinformationen fehlten.
                           Wenn angegeben, wird diese mit 'message' (Identitätsinformationen) kombiniert.
            thread_id: (Optional) Die Thread-ID für die Konversation. Wird für State-Tracking verwendet.
        
        Returns:
            Ein Dictionary mit Status, Nachricht und Metadaten der Verarbeitung:
            - status: 'missing_identity', 'unsupported', 'completed', 'waiting_for_identity', oder 'error'
            - message: Die Antwortnachricht vom Workflow
            - is_historian_answer: (Optional) True wenn die 'message' die direkte Historian-Antwort ist
            - direct_answer: (Optional) Die direkte Antwort vom Historian (falls is_historian_answer=True)
            - metadata: Zusätzliche Metadaten mit folgenden Feldern:
              * category: Die Kategorie der Anfrage ('Frage zur Historie von AI', 'O365 Frage', etc.)
              * missing_fields: Liste fehlender Felder (wenn status='missing_identity')
              * missing_labels: Labels für fehlende Felder (wenn status='missing_identity')
              * original_message: (Optional) Die ursprüngliche Anfrage, wenn identity fehlte
            - payload: Optional versendetes Payload (wenn Ticket erstellt wurde)
            
        WICHTIGE REGEL FÜR AI-HISTORIE-FRAGEN:
        Wenn 'is_historian_answer' = True ODER 'metadata.category' = 'Frage zur Historie von AI':
        - Die 'message' (oder 'direct_answer') ist die KOMPLETTE Antwort vom Historian-Executor
        - Diese Antwort muss EXAKT so an den Benutzer weitergegeben werden, OHNE Änderungen
        - Füge KEINE zusätzlichen Texte hinzu wie 'Ihr Ticket wurde erfolgreich...'
        - Die Antwort ist bereits vollständig und beantwortet die Frage des Benutzers
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Determine state key: use thread_id if provided, otherwise use message hash
        # If original_message is provided, use it to find the state
        state_key = None
        if original_message:
            # When original_message is provided, find the state by the original message hash
            state_key = _get_state_key(thread_id, original_message)
        else:
            # For new messages, use thread_id or message hash
            state_key = _get_state_key(thread_id, message)
        
        # Get current state for this thread/message
        with _state_lock:
            thread_state = _identity_state.get(state_key, {
                "waiting_for_identity": False,
                "original_message": None,
            })
        
        # If we're waiting for identity and original_message is not provided,
        # check if the message matches the required format
        if thread_state["waiting_for_identity"] and not original_message:
            # Check if message matches the required format: "Name, Vorname, E-Mail-Adresse"
            message_stripped = message.strip()
            if not _IDENTITY_FORMAT_PATTERN.match(message_stripped):
                # Reject the query - we're still waiting for identity in the correct format
                logger.debug(f"Rejecting query - waiting for identity but message doesn't match format: {repr(message)}")
                return {
                    "status": "waiting_for_identity",
                    "message": (
                        "Bitte geben Sie Ihre Angaben im Format Name, Vorname, E-Mail-Adresse an. "
                        "Beispiel: Müller, Hans, hans@example.com\n\n"
                        "Ich kann Ihre Anfrage erst bearbeiten, nachdem Sie Ihre Identitätsinformationen "
                        "im korrekten Format bereitgestellt haben."
                    ),
                    "metadata": {
                        "waiting_for_identity": True,
                        "original_message": thread_state["original_message"],
                    },
                }
        
        # If original_message is provided, combine it with the current message (identity info)
        # This handles the case where the user provides identity in a follow-up message
        if original_message:
            # Combine: original request + identity information
            # Format: original message, then a separator, then identity info
            # This allows IdentityExtractorExecutor to extract from the identity part
            # while preserving the original request for classification
            combined_message = f"{original_message}\n\n---\n{message}"
        else:
            # Normal case: message contains everything
            combined_message = message
        
        # Pass the combined message - let the workflow's IdentityExtractorExecutor handle extraction
        ticket_input = TicketInput(message=combined_message)
        
        # Debug logging
        logger.debug(f"process_ticket called with message: {repr(message)}")
        logger.debug(f"ticket_input.message: {repr(ticket_input.message)}")
        logger.debug(f"thread_state: {thread_state}")
        
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
            
            # Store original_message in metadata if it was provided, so the agent can remember it
            if original_message:
                metadata["original_message"] = original_message
            
            # Update state based on result
            with _state_lock:
                if result.status == "missing_identity":
                    # We're now waiting for identity - store state
                    # Use the combined_message (or original if provided) as the key
                    original_msg = combined_message if not original_message else original_message
                    state_key_for_storage = _get_state_key(thread_id, original_msg)
                    _identity_state[state_key_for_storage] = {
                        "waiting_for_identity": True,
                        "original_message": original_msg,
                    }
                    logger.debug(f"Set waiting_for_identity=True for state_key {state_key_for_storage}")
                elif result.status == "completed":
                    # Identity is complete - clear waiting state for this key and related keys
                    # Clear all states that might be related (by checking if original_message matches)
                    keys_to_remove = []
                    for key, state in _identity_state.items():
                        if state.get("original_message") == combined_message or state.get("original_message") == original_message:
                            keys_to_remove.append(key)
                    for key in keys_to_remove:
                        del _identity_state[key]
                    logger.debug(f"Cleared waiting_for_identity for {len(keys_to_remove)} state(s)")
            
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
        name="ticket-support-agent",
        description="IT-Support-Assistent für das Obungi Ticket-System",
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
            "   - Wenn 'status' = 'missing_identity' ODER 'status' = 'waiting_for_identity':\n"
            "     * MERKE DIR die ursprüngliche Anfrage des Benutzers (die Nachricht, die du an 'process_ticket' übergeben hast)\n"
            "     * Frage IMMER nach ALLEN drei Feldern: Name, Vorname, E-Mail-Adresse\n"
            "     * Verwende die Labels aus 'metadata.missing_labels' für die Frage (falls vorhanden)\n"
            "     * WICHTIG: Bitte den Benutzer, die Informationen im Format 'Name, Vorname, E-Mail-Adresse' anzugeben (komma-getrennt)\n"
            "     * Beispiel: 'Bitte geben Sie Ihre Angaben im Format Name, Vorname, E-Mail-Adresse an. Beispiel: Müller, Hans, hans@example.com'\n"
            "     * KRITISCH: Wenn der Benutzer eine NEUE Anfrage stellt (nicht im Format 'Name, Vorname, E-Mail-Adresse'),\n"
            "       dann rufe 'process_ticket' NICHT auf. Stattdessen erinnere den Benutzer daran, dass er zuerst\n"
            "       seine Identitätsinformationen im korrekten Format bereitstellen muss.\n"
            "     * Wenn der Benutzer die Identitätsinformationen liefert (z.B. 'Tran, Huy, khanhhuy288@gmail.com'):\n"
            "       → Rufe 'process_ticket' erneut auf mit:\n"
            "         - message: Die Identitätsinformationen vom Benutzer (z.B. 'Tran, Huy, khanhhuy288@gmail.com')\n"
            "         - original_message: Die ursprüngliche Anfrage, die du dir gemerkt hast\n"
            "     * Dies stellt sicher, dass die ursprüngliche Anfrage zusammen mit den Identitätsinformationen verarbeitet wird\n\n"
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
            "   - Für die ERSTE Anfrage: Übergebe nur 'message' mit der vollständigen Benutzernachricht\n"
            "   - Wenn 'status' = 'missing_identity' zurückkommt:\n"
            "     * MERKE DIR die ursprüngliche Nachricht (die du an 'process_ticket' übergeben hast)\n"
            "     * Frage den Benutzer nach Identitätsinformationen\n"
            "   - Wenn der Benutzer Identitätsinformationen liefert:\n"
            "     * Rufe 'process_ticket' auf mit:\n"
            "       - message: Die Identitätsinformationen (z.B. 'Tran, Huy, khanhhuy288@gmail.com')\n"
            "       - original_message: Die ursprüngliche Anfrage, die du dir gemerkt hast\n"
            "   - Das Workflow-System kombiniert automatisch die ursprüngliche Anfrage mit den Identitätsinformationen\n"
            "   - WICHTIG: Identitätsinformationen MÜSSEN im Format 'Name, Vorname, E-Mail-Adresse' (komma-getrennt) vorliegen\n\n"
            "5. **ENTSCHEIDUNGSBAUM nach process_ticket Aufruf:**\n"
            "   Schritt 1: Prüfe 'is_historian_answer' oder 'metadata.category'\n"
            "   Schritt 2a: Wenn 'is_historian_answer' = True ODER 'metadata.category' = 'Frage zur Historie von AI':\n"
            "              → Verwende 'direct_answer' (falls vorhanden) oder 'message' EXAKT so\n"
            "              → Keine zusätzlichen Texte, keine Umformulierung\n"
            "   Schritt 2b: Wenn 'status' = 'completed' UND category != 'Frage zur Historie von AI':\n"
            "              → Antworte: 'Ihr Ticket wurde erfolgreich an das IT-Team übergeben. Sie erhalten eine Rückmeldung per E-Mail.'\n"
            "   Schritt 2c: Wenn 'status' = 'missing_identity' ODER 'status' = 'waiting_for_identity':\n"
            "              → MERKE DIR die ursprüngliche Nachricht (die du an 'process_ticket' übergeben hast)\n"
            "              → Frage nach ALLEN drei Feldern im Format 'Name, Vorname, E-Mail-Adresse'\n"
            "              → KRITISCH: Wenn der Benutzer eine NEUE Anfrage stellt (nicht im Format), rufe 'process_ticket' NICHT auf.\n"
            "                Erinnere stattdessen den Benutzer daran, zuerst Identitätsinformationen bereitzustellen.\n"
            "              → Wenn der Benutzer Identitätsinformationen liefert, rufe 'process_ticket' auf mit:\n"
            "                 message=<Identitätsinformationen>, original_message=<ursprüngliche Nachricht>\n"
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

