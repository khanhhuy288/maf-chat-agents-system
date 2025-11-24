from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from agent_framework import AgentExecutor, Case, ChatAgent, Default, Workflow, WorkflowBuilder
from agent_framework.azure import AzureOpenAIChatClient

from chat_agents_system.agents import (
    ClassificationExecutor,
    DispatcherExecutor,
    HistorianExecutor,
    IdentityExtractorExecutor,
    ResponseFormatterExecutor,
    ValidationExecutor,
)
from chat_agents_system.config import settings
from chat_agents_system.schemas import (
    TicketCategory,
    TicketContext,
    TicketInput,
    TicketResponse,
)
from chat_agents_system.utils import get_logger

# Simplified thread-based state tracking for identity requests
# Uses Microsoft Agent Framework's conversation/thread management pattern
# Maps thread_id -> {"waiting_for_identity": bool, "original_message": str | None}
# Also tracks by message hash as fallback when thread_id is not available (DevUI)
_identity_state: dict[str, dict[str, Any]] = {}
_identity_state_by_message: dict[str, dict[str, Any]] = {}  # Fallback: message hash -> state
_state_lock = threading.Lock()

# Pattern to match the required identity format: "Name, Vorname, E-Mail-Adresse"
# Exported for use in API routes
IDENTITY_FORMAT_PATTERN = re.compile(
    r"^[^,]+,\s*[^,]+,\s*[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.IGNORECASE
)

# Instructions for the conversational agent
# SIMPLIFIED: Agent always calls process_ticket, function handles all logic
_CONVERSATIONAL_AGENT_INSTRUCTIONS = (
    "Du bist ein freundlicher IT-Support-Assistent für das Ticket-System. "
    "Du hilfst Benutzern bei IT-Anfragen und verarbeitest diese durch ein internes Workflow-System.\n\n"
    "WICHTIGE VERHALTENSREGELN:\n\n"
    "1. **ALLE Benutzernachrichten verarbeiten:**\n"
    "   - Für JEDE Benutzernachricht rufst du IMMER die Funktion 'process_ticket' auf\n"
    "   - Übergebe die vollständige Benutzernachricht im 'message' Parameter\n"
    "   - Die Funktion prüft automatisch alles und gibt dir die richtige Antwort zurück\n"
    "   - Du musst NICHT entscheiden, ob die Nachricht eine Anfrage ist oder Identitätsinformationen\n"
    "   - Die Funktion erkennt automatisch das Format und verarbeitet entsprechend\n\n"
    "2. **Antworten basierend auf Workflow-Ergebnis:**\n"
    "   Nach jedem 'process_ticket' Aufruf gibst du die Antwort aus 'message' an den Benutzer weiter:\n"
    "   - Die Funktion gibt dir IMMER die richtige Antwort in 'message' zurück\n"
    "   - Gib die 'message' EXAKT so weiter, wie sie ist - keine Änderungen, keine Ergänzungen\n"
    "   - Die Funktion hat bereits alle Logik verarbeitet und die passende Antwort generiert\n"
    "   - Wenn 'is_historian_answer' = True: Die 'message' ist die komplette Historian-Antwort, gib sie 1:1 weiter\n"
    "   - Wenn 'status' = 'waiting_for_identity': Die 'message' enthält bereits die Aufforderung, gib sie 1:1 weiter\n"
    "   - Wenn 'status' = 'completed': Die 'message' enthält die Erfolgsmeldung, gib sie 1:1 weiter\n"
    "   - Wenn 'status' = 'unsupported' oder 'error': Die 'message' enthält die Fehlermeldung, gib sie 1:1 weiter\n"
    "   - MERKE: Du musst NICHT entscheiden, was zu tun ist - die Funktion hat das bereits gemacht\n\n"
    "3. **Ton und Stil:**\n"
    "   - Sei immer freundlich und professionell\n"
    "   - Antworte auf Deutsch\n"
    "   - Die Antworten kommen bereits von der Funktion, du musst sie nur weitergeben\n\n"
    "ZUSAMMENFASSUNG - WICHTIG:\n"
    "- Für JEDE Benutzernachricht: Rufe IMMER 'process_ticket' auf\n"
    "- Die Funktion prüft automatisch alles (Format, Identität, etc.)\n"
    "- Gib die 'message' aus dem Ergebnis EXAKT so weiter\n"
    "- Du musst KEINE Entscheidungen treffen - die Funktion macht alles\n\n"
    "Beispiel-Ablauf:\n"
    "1. Benutzer sendet eine Nachricht\n"
    "2. Du rufst 'process_ticket(message=<Benutzernachricht>)' auf\n"
    "3. Funktion gibt zurück: {status: '...', message: '...'}\n"
    "4. Du gibst die 'message' EXAKT so an den Benutzer weiter\n"
    "5. Fertig - keine weiteren Entscheidungen nötig!"
)


def _hash_message(message: str) -> str:
    """Create a simple hash of a message for state tracking."""
    import hashlib
    return hashlib.md5(message.encode('utf-8')).hexdigest()[:16]


def get_thread_state(thread_id: str | None, message: str | None = None) -> dict[str, Any]:
    """Get state for a thread. Returns default state if thread_id is None or not found.
    
    Uses Microsoft Agent Framework's conversation management pattern:
    - State is tracked per conversation/thread_id (preferred)
    - Falls back to message-based tracking when thread_id is not available (DevUI)
    - Returns default (not waiting) state when neither is found
    """
    with _state_lock:
        # First try thread_id-based tracking
        if thread_id:
            state = _identity_state.get(thread_id)
            if state:
                return state
        
        # Fallback: check if any state is waiting (for DevUI when thread_id not available)
        # This handles the case where DevUI doesn't pass thread_id but we still need to track state
        if message:
            message_hash = _hash_message(message)
            state = _identity_state_by_message.get(message_hash)
            if state:
                return state
            
            # Check all waiting states - if any are waiting, assume we're in that conversation
            # For DevUI, there's typically only one active conversation, so this is safe
            # We prioritize the most recent waiting state (last in dict, but order isn't guaranteed)
            # The key point: if ANY state is waiting, we should check format before processing
            for state in _identity_state.values():
                if state.get("waiting_for_identity"):
                    return state
            
            # Also check message-based states
            for state in _identity_state_by_message.values():
                if state.get("waiting_for_identity"):
                    return state
        
        # Default: not waiting
        return {
            "waiting_for_identity": False,
            "original_message": None,
        }


def set_thread_state(thread_id: str | None, waiting_for_identity: bool, original_message: str | None = None) -> None:
    """Set state for a thread. Uses thread_id if available, otherwise falls back to message-based tracking.
    
    Uses Microsoft Agent Framework's conversation management pattern:
    - State is stored per conversation/thread_id (preferred)
    - Falls back to message-based tracking when thread_id is not available (DevUI)
    """
    with _state_lock:
        if waiting_for_identity:
            state = {
                "waiting_for_identity": True,
                "original_message": original_message,
            }
            if thread_id:
                _identity_state[thread_id] = state
            elif original_message:
                # Fallback: track by message hash when thread_id not available
                message_hash = _hash_message(original_message)
                _identity_state_by_message[message_hash] = state
        else:
            # Clear state when identity is complete
            if thread_id:
                _identity_state.pop(thread_id, None)
            elif original_message:
                # Clear message-based state
                message_hash = _hash_message(original_message)
                _identity_state_by_message.pop(message_hash, None)




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
        
        Diese Funktion wird für JEDE Benutzernachricht aufgerufen. Sie prüft automatisch:
        - Ob Identitätsinformationen im korrekten Format vorliegen
        - Ob wir auf Identitätsinformationen warten
        - Ob die Nachricht eine neue Anfrage oder Identitätsinformationen enthält
        
        Die Funktion gibt IMMER eine vollständige Antwort in 'message' zurück, die direkt
        an den Benutzer weitergegeben werden kann.
        
        Args:
            message: Die Benutzernachricht (kann eine Anfrage oder Identitätsinformationen sein)
            original_message: (Optional) Wird automatisch aus dem Thread-State übernommen, falls vorhanden
            thread_id: (Optional) Die Thread-ID für die Konversation. Wird für State-Tracking verwendet.
        
        Returns:
            Ein Dictionary mit Status und vollständiger Antwortnachricht:
            - status: 'missing_identity', 'unsupported', 'completed', 'waiting_for_identity', oder 'error'
            - message: Die vollständige Antwortnachricht, die EXAKT so an den Benutzer weitergegeben werden soll
            - is_historian_answer: (Optional) True wenn die 'message' die direkte Historian-Antwort ist
            - metadata: Zusätzliche Metadaten (category, etc.)
            - payload: Optional versendetes Payload (wenn Ticket erstellt wurde)
        """
        from chat_agents_system.utils import get_logger
        
        logger = get_logger(__name__)
        logger.debug(f"process_ticket called with message: {repr(message[:100])}, original_message: {repr(original_message[:100] if original_message else None)}, thread_id: {thread_id}")
        
        # Check if message matches identity format (STRICT: only "Name, Vorname, E-Mail-Adresse")
        message_stripped = message.strip()
        is_identity_format = IDENTITY_FORMAT_PATTERN.match(message_stripped)
        
        # Determine original_message: from parameter, from thread state, or from any waiting state (fallback)
        resolved_original_message: str | None = original_message
        
        # CRITICAL: Check if we're waiting for identity (from thread_id OR from any waiting state)
        # When waiting for identity, ONLY accept the exact format "Name, Vorname, E-Mail-Adresse"
        # Reject everything else, including natural language identity or new queries
        waiting_for_identity = False
        waiting_thread_state = None
        
        if thread_id:
            # We have thread_id - check state for this specific thread
            thread_state = get_thread_state(thread_id)
            if thread_state.get("waiting_for_identity"):
                waiting_for_identity = True
                waiting_thread_state = thread_state
        else:
            # No thread_id - check for waiting states (fallback for DevUI)
            # We check regardless of format because:
            # - If format matches and we're waiting, we need original_message
            # - If format doesn't match and we're waiting, we need to reject
            thread_state = get_thread_state(None, message=message)
            if thread_state.get("waiting_for_identity"):
                waiting_for_identity = True
                waiting_thread_state = thread_state
        
        if waiting_for_identity:
            logger.debug(
                f"Waiting for identity detected. Thread ID: {thread_id}, "
                f"Original message: {repr(waiting_thread_state.get('original_message', '')[:50]) if waiting_thread_state else 'None'}"
            )
        
        # If waiting for identity and message doesn't match STRICT format, reject it immediately
        # This prevents the workflow from running and extracting identity from natural language
        if waiting_for_identity and not is_identity_format:
            logger.warning(
                f"REJECTING: Waiting for identity but message doesn't match strict format. "
                f"Message: {repr(message[:150])}, "
                f"Thread ID: {thread_id}, "
                f"Is format match: {is_identity_format}"
            )
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
                    "original_message": waiting_thread_state["original_message"] if waiting_thread_state else None,
                },
            }
        
        # If identity format detected and we're waiting, get original_message from state
        if is_identity_format and waiting_for_identity and waiting_thread_state:
            if not resolved_original_message:
                resolved_original_message = waiting_thread_state["original_message"]
                logger.debug(f"Identity format detected, using original_message from state: {repr(resolved_original_message[:50] if resolved_original_message else 'None')}")
        
        # When we have original_message and current message is identity format:
        # Pass original_message through TicketInput so identity extractor can use it
        # This is simpler than combining and splitting with separators
        ticket_input = TicketInput(
            message=message,
            original_message=resolved_original_message if resolved_original_message else None
        )
        if resolved_original_message:
            logger.debug(f"Passing original_message through TicketInput: {repr(resolved_original_message[:50])}")
        logger.debug(f"ticket_input.message length: {len(ticket_input.message)}")
        
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
            if resolved_original_message:
                metadata["original_message"] = resolved_original_message
            
            # Update state based on result (works with or without thread_id)
            if result.status == "missing_identity":
                # We're now waiting for identity - store the original message
                original_msg = resolved_original_message if resolved_original_message else message
                set_thread_state(thread_id, waiting_for_identity=True, original_message=original_msg)
                logger.debug(
                    f"Set waiting_for_identity=True. Thread ID: {thread_id}, "
                    f"Original message length: {len(original_msg) if original_msg else 0}"
                )
            elif result.status == "completed":
                # Identity is complete - clear waiting state
                original_msg = resolved_original_message if resolved_original_message else message
                set_thread_state(thread_id, waiting_for_identity=False, original_message=original_msg)
                logger.debug(f"Cleared waiting_for_identity. Thread ID: {thread_id}")
            
            # For AI history questions, the message IS the answer from HistorianExecutor
            # Make this explicit in the response
            response = {
                "status": result.status,
                "message": result.message,
                "metadata": metadata,
                "payload": result.payload,
            }
            
            # Add explicit flag for AI history to make it crystal clear
            # The message field already contains the direct answer, no need to duplicate it
            if category == "Frage zur Historie von AI" and result.status == "completed":
                response["is_historian_answer"] = True
            
            return response
        except Exception as e:
            return {
                "status": "error",
                "message": f"Fehler bei der Verarbeitung: {str(e)}",
            }
    
    return chat_client.create_agent(
        name="Ticket Support Agent",
        description="IT-Support-Assistent für das Ticket-System",
        instructions=_CONVERSATIONAL_AGENT_INSTRUCTIONS,
        tools=[process_ticket],
    )


def create_ticket_workflow(*, simulate_dispatch: bool = True) -> Workflow:
    chat_client = create_chat_client()

    # IdentityExtractorExecutor now handles intake functionality (normalizing input and creating TicketContext)
    identity = IdentityExtractorExecutor(chat_client)
    validation = ValidationExecutor()
    classification = ClassificationExecutor(chat_client)
    historian = HistorianExecutor(chat_client)
    dispatcher = DispatcherExecutor(
        settings.ticket_logic_app_url, simulate_only=simulate_dispatch
    )
    formatter = ResponseFormatterExecutor()

    # Condition functions for routing
    def is_ai_history(context: TicketContext) -> bool:
        """Check if ticket is AI history category."""
        return context.category == TicketCategory.AI_HISTORY if context.category else False

    def is_dispatchable(context: TicketContext) -> bool:
        """Check if ticket should be dispatched (O365, HARDWARE, LOGIN)."""
        if not context.category:
            return False
        return context.category in {
            TicketCategory.O365,
            TicketCategory.HARDWARE,
            TicketCategory.LOGIN,
        }

    workflow = (
        WorkflowBuilder(
            name="Ticket Workflow",
            description="Branching workflow with category-based routing after classification.",
        )
        .set_start_executor(identity)
        .add_edge(identity, validation)
        .add_edge(validation, classification)
        # Branch after classification based on category
        .add_switch_case_edge_group(
            classification,
            [
                Case(condition=is_ai_history, target=historian),
                Case(condition=is_dispatchable, target=dispatcher),
                Default(target=formatter),  # OTHER category - early exit
            ],
        )
        # AI_HISTORY path: historian → dispatcher → formatter
        .add_edge(historian, dispatcher)
        # All dispatched paths converge to formatter
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

