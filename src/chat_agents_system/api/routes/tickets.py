"""Ticket processing endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chat_agents_system.schemas import TicketInput, TicketResponse
from chat_agents_system.utils import get_logger
from chat_agents_system import workflow as workflow_module

logger = get_logger(__name__)
router = APIRouter()


class TicketRequest(BaseModel):
    """Request model for ticket processing.
    
    Supports two modes:
    1. Single request: Include identity fields (name, vorname, email) directly
    2. Two-step flow: Omit identity, get 'missing_identity' response, then send follow-up
       with same thread_id and identity in format "Name, Vorname, Email"
    """

    message: str = Field(
        ...,
        description=(
            "The user's ticket message. For follow-up identity requests, use format: "
            "'Name, Vorname, Email' (e.g., 'Müller, Hans, hans@example.com')"
        ),
        json_schema_extra={"example": "Ich habe ein Problem mit meinem Login"},
    )
    name: str | None = Field(
        None,
        description=(
            "User's last name (optional). If omitted, system will attempt extraction "
            "from message or request follow-up."
        ),
        json_schema_extra={"example": "Müller"},
    )
    vorname: str | None = Field(
        None,
        description=(
            "User's first name (optional). If omitted, system will attempt extraction "
            "from message or request follow-up."
        ),
        json_schema_extra={"example": "Hans"},
    )
    email: str | None = Field(
        None,
        description=(
            "User's email address (optional). If omitted, system will attempt "
            "extraction from message or request follow-up."
        ),
        json_schema_extra={"example": "hans.mueller@example.com"},
    )
    thread_id: str | None = Field(
        None,
        description=(
            "Thread ID for conversation continuity. "
            "Two-step identity capture REQUIRES supplying the same thread_id returned in the "
            "initial missing_identity response. Without a thread_id, all identity fields must be "
            "included up front. Example: 'thread-abc123'."
        ),
        json_schema_extra={"example": "thread-abc123"},
    )
    simulate_dispatch: bool = Field(
        True,
        description=(
            "Dispatcher simulation toggle. Forced to True for the current demo build so that "
            "no requests are sent to the Logic App endpoint, even if False is provided."
        ),
        json_schema_extra={"example": True},
    )


class TicketResponseModel(BaseModel):
    """Response model for ticket processing.
    
    Status values:
    - 'completed': Ticket processed successfully
    - 'missing_identity': Identity information required (send follow-up with thread_id)
    - 'waiting_for_identity': Still waiting for identity in correct format
    - 'unsupported': Request category not supported
    - 'error': Processing error occurred
    """

    status: str = Field(
        ...,
        description=(
            "Processing status: 'completed', 'missing_identity', 'waiting_for_identity', "
            "'unsupported', or 'error'"
        ),
        json_schema_extra={"example": "completed"},
    )
    message: str = Field(
        ...,
        description=(
            "Response message. For AI history questions, this contains the full answer. "
            "For missing_identity status, this contains instructions for providing identity."
        ),
        json_schema_extra={"example": "Ihr Ticket wurde erfolgreich an das IT-Team übergeben."},
    )
    payload: dict[str, Any] | None = Field(
        None,
        description="Dispatch payload sent to Logic App (if applicable and not simulated)",
        json_schema_extra={
            "example": {
                "name": "Müller",
                "vorname": "Hans",
                "email": "hans@example.com",
                "kategorie": "Login",
            }
        },
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Additional metadata. May include thread_id, category, missing_fields, "
            "missing_labels, original_message, etc."
        ),
        json_schema_extra={
            "example": {"category": "Probleme bei der Anmeldung", "thread_id": "thread-123"}
        },
    )


@router.post(
    "/tickets",
    response_model=TicketResponseModel,
    summary="Process a ticket through the workflow system",
    description="""
    Process a ticket through the multi-agent workflow system. The endpoint mirrors the DevUI
    behavior: identity must be captured first, and `thread_id` enables the server-side
    identity loop so the workflow can resume once the user submits the strict format
    `Name, Vorname, E-Mail-Adresse`. Dispatcher calls always run in **simulation mode** in
    this demo build, so the Logic App is never invoked.
    
    ## Workflow Steps
    1. **Identity Extraction** – Normalizes input, preserves the original message and pulls `name`, `vorname`, `email`.
    2. **Validation** – Returns `status="missing_identity"` whenever a field is absent.
    3. **Classification** – Categorizes into AI history, O365, hardware, login, or other and produces a short summary.
    4. **Category Handling** – Historian answers AI history questions, Dispatcher posts dispatchable tickets, OTHER exits early.
    5. **Response Formatting** – Produces the final `TicketResponse` (`completed`, `unsupported`, etc.).
    
    ## Two-Step Flow (Missing Identity)
    
    **Step 1: Initial Request (no identity yet)**
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "thread_id": "thread-123"
    }
    ```
    → Response: `status = "missing_identity"`, metadata includes `thread_id`, `missing_fields`,
    `waiting_for_identity = true`.
    
    **Step 2: Follow-up with strict identity format**
    ```json
    {
      "message": "Müller, Hans, hans@example.com",
      "thread_id": "thread-123"
    }
    ```
    → The API automatically reuses the stored original request and continues the workflow.
    
    Ohne `thread_id` ist kein zweistufiger Ablauf möglich – liefern Sie dann alle Identitätsfelder
    direkt mit der ersten Anfrage.
    
    ## Response Statuses
    
    - `completed` – Ticket processed successfully (includes dispatcher payload + metadata).
    - `missing_identity` – Identity required; client should resend only the strict identity string with the same `thread_id`.
    - `waiting_for_identity` – A strict identity string was expected but not provided.
    - `unsupported` – Category `Sonstiges` (no dispatch).
    - `error` – Processing failure (the request returns HTTP 200 with `status="error"` unless an exception occurs, which surfaces as HTTP 500).
    - HTTP 400 – Raised when a client sends an identity-only follow-up without the `thread_id` returned in the prior `missing_identity` response.
    
    ## AI History Questions
    
    When the classifier labels the ticket as `"Frage zur Historie von AI"`, the Historian agent
    generates the full German answer; the response `message` already contains the final text.
    
    ## Request Examples
    
    **Single Request with Identity**
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "name": "Müller",
      "vorname": "Hans",
      "email": "hans@example.com",
      "simulate_dispatch": true
    }
    ```
    
    **Two-Step Flow**
    
    Step 1 – Missing identity:
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "thread_id": "thread-123"
    }
    ```
    
    Step 2 – Strict identity reply (must include identical `thread_id`):
    ```json
    {
      "message": "Müller, Hans, hans@example.com",
      "thread_id": "thread-123"
    }
    ```
    """,
    responses={
        200: {
            "description": "Ticket processed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "completed",
                        "message": "Ihr Ticket wurde erfolgreich an das IT-Team übergeben.",
                        "metadata": {"category": "Probleme bei der Anmeldung", "thread_id": "thread-123"},
                        "payload": {"name": "Müller", "vorname": "Hans", "email": "hans@example.com"}
                    }
                }
            }
        },
        400: {
            "description": "Client error (e.g., missing thread_id for identity follow-up)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Identity follow-ups require the same thread_id provided in the previous "
                            "missing_identity response. Resend the identity string with that thread_id."
                        )
                    }
                }
            },
        },
        500: {
            "description": "Processing error",
            "content": {
                "application/json": {
                    "example": {"detail": "Error processing ticket: <error message>"}
                }
            }
        }
    }
)
async def process_ticket(request: TicketRequest) -> TicketResponseModel:
    """Process a ticket through the workflow system."""
    try:
        logger.info(f"Processing ticket request: message={request.message[:100]}...")
        message_stripped = request.message.strip()

        # Identity-only follow-ups must supply the thread_id that was returned with the
        # missing_identity response so we can recover the stored original message.
        if (
            not request.thread_id
            and workflow_module.IDENTITY_FORMAT_PATTERN.match(message_stripped)
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Identity follow-ups require the same thread_id provided in the previous "
                    "missing_identity response. Resend the identity string with that thread_id."
                ),
            )
        
        # Determine whether this thread is waiting for strict identity info
        original_message: str | None = None
        if request.thread_id:
            thread_state = workflow_module.get_thread_state(request.thread_id)
            if thread_state["waiting_for_identity"]:
                message_stripped = request.message.strip()
                if workflow_module.IDENTITY_FORMAT_PATTERN.match(message_stripped):
                    original_message = thread_state["original_message"]
                    if not original_message:
                        logger.warning(
                            "Thread %s expects identity but original_message is missing",
                            request.thread_id,
                        )
                else:
                    return TicketResponseModel(
                        status="waiting_for_identity",
                        message=(
                            "Bitte geben Sie Ihre Angaben im Format Name, Vorname, E-Mail-Adresse an. "
                            "Beispiel: Müller, Hans, hans@example.com\n\n"
                            "Ich kann Ihre Anfrage erst bearbeiten, nachdem Sie Ihre Identitätsinformationen "
                            "im korrekten Format bereitgestellt haben."
                        ),
                        metadata={
                            "waiting_for_identity": True,
                            "original_message": thread_state["original_message"],
                            "thread_id": request.thread_id,
                        },
                    )
        
        if not request.simulate_dispatch:
            logger.info(
                "simulate_dispatch=False was requested but is ignored; dispatcher runs in "
                "simulation mode for the current demo build."
            )
        workflow = workflow_module.create_ticket_workflow(simulate_dispatch=True)
        
        ticket_input = TicketInput(
            message=request.message,
            name=request.name,
            vorname=request.vorname,
            email=request.email,
            original_message=original_message,
        )
        
        # Run workflow
        events = await workflow.run(ticket_input)
        outputs = events.get_outputs()
        
        if not outputs:
            raise HTTPException(
                status_code=500,
                detail="Workflow did not produce any output"
            )
        
        # Get the final response (from ResponseFormatterExecutor)
        result: TicketResponse = outputs[-1]
        
        # Update state based on result (simplified thread-based approach)
        if request.thread_id:
            original_msg = original_message if original_message else request.message
            if result.status == "missing_identity":
                workflow_module.set_thread_state(
                    request.thread_id,
                    waiting_for_identity=True,
                    original_message=original_msg,
                )
                logger.debug(f"Set waiting_for_identity=True for thread_id {request.thread_id}")
            else:
                workflow_module.set_thread_state(
                    request.thread_id,
                    waiting_for_identity=False,
                    original_message=original_msg,
                )
                logger.debug(
                    "Cleared waiting_for_identity for thread_id %s after status %s",
                    request.thread_id,
                    result.status,
                )
        
        logger.info(f"Ticket processed successfully: status={result.status}")
        
        # Build response metadata
        response_metadata = result.metadata or {}
        if request.thread_id:
            response_metadata["thread_id"] = request.thread_id
        
        # Convert to response model
        return TicketResponseModel(
            status=result.status,
            message=result.message,
            payload=result.payload,
            metadata=response_metadata,
        )
        
    except HTTPException as exc:
        raise exc
    except Exception as e:
        logger.exception(f"Error processing ticket: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing ticket: {str(e)}"
        ) from e

