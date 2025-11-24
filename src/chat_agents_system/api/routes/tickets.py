"""Ticket processing endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from chat_agents_system.schemas import TicketInput, TicketResponse
from chat_agents_system.utils import get_logger
from chat_agents_system.workflow import (
    IDENTITY_FORMAT_PATTERN,
    create_ticket_workflow,
    get_thread_state,
    set_thread_state,
)

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
        description="The user's ticket message. For follow-up identity requests, use format: 'Name, Vorname, Email' (e.g., 'Müller, Hans, hans@example.com')",
        example="Ich habe ein Problem mit meinem Login"
    )
    name: str | None = Field(
        None,
        description="User's last name (optional). If omitted, system will attempt extraction from message or request follow-up.",
        example="Müller"
    )
    vorname: str | None = Field(
        None,
        description="User's first name (optional). If omitted, system will attempt extraction from message or request follow-up.",
        example="Hans"
    )
    email: str | None = Field(
        None,
        description="User's email address (optional). If omitted, system will attempt extraction from message or request follow-up.",
        example="hans.mueller@example.com"
    )
    thread_id: str | None = Field(
        None,
        description=(
            "Thread ID for conversation continuity (optional). "
            "Use the same thread_id across multiple requests to maintain conversation state. "
            "Required for follow-up identity messages. "
            "Example: 'thread-123' or any unique identifier."
        ),
        example="thread-abc123"
    )
    simulate_dispatch: bool = Field(
        True,
        description=(
            "Whether to simulate dispatch to Logic App (default: True). "
            "Set to False to actually send HTTP requests to the configured Logic App endpoint. "
            "Use True for testing to avoid external API calls."
        ),
        example=True
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
        description="Processing status: 'completed', 'missing_identity', 'waiting_for_identity', 'unsupported', or 'error'",
        example="completed"
    )
    message: str = Field(
        ...,
        description=(
            "Response message. For AI history questions, this contains the full answer. "
            "For missing_identity status, this contains instructions for providing identity."
        ),
        example="Ihr Ticket wurde erfolgreich an das IT-Team übergeben."
    )
    payload: dict[str, Any] | None = Field(
        None,
        description="Dispatch payload sent to Logic App (if applicable and not simulated)",
        example={"name": "Müller", "vorname": "Hans", "email": "hans@example.com", "kategorie": "Login"}
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Additional metadata. May include: "
            "thread_id (if provided), category, missing_fields, missing_labels, "
            "original_message (for follow-up requests), etc."
        ),
        example={"category": "Probleme bei der Anmeldung", "thread_id": "thread-123"}
    )


@router.post(
    "/tickets",
    response_model=TicketResponseModel,
    summary="Process a ticket through the workflow system",
    description="""
    Process a ticket through the multi-agent workflow system. The endpoint mirrors the DevUI
    behavior: identity must be captured first, and `thread_id` enables the server-side
    identity loop so the workflow can resume once the user submits the strict format
    `Name, Vorname, E-Mail-Adresse`.
    
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
    
    Without a `thread_id`, the API is stateless: include identity fields up front or set
    `original_message` manually when sending follow-up identity information.
    
    ## Response Statuses
    
    - `completed` – Ticket processed successfully (includes dispatcher payload + metadata).
    - `missing_identity` – Identity required; client should resend only the strict identity string with the same `thread_id`.
    - `waiting_for_identity` – A strict identity string was expected but not provided.
    - `unsupported` – Category `Sonstiges` (no dispatch).
    - `error` – Processing failure (the request returns HTTP 200 with `status="error"` unless an exception occurs, which surfaces as HTTP 500).
    
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
    
    Step 2 – Strict identity reply:
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
        
        # Determine whether this thread is waiting for strict identity info
        original_message: str | None = None
        if request.thread_id:
            thread_state = get_thread_state(request.thread_id)
            if thread_state["waiting_for_identity"]:
                message_stripped = request.message.strip()
                if IDENTITY_FORMAT_PATTERN.match(message_stripped):
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
        
        workflow = create_ticket_workflow(simulate_dispatch=request.simulate_dispatch)
        
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
            if result.status == "missing_identity":
                # Store original message for this thread
                original_msg = original_message if original_message else request.message
                set_thread_state(request.thread_id, waiting_for_identity=True, original_message=original_msg)
                logger.debug(f"Set waiting_for_identity=True for thread_id {request.thread_id}")
            elif result.status == "completed":
                # Clear waiting state for this thread
                set_thread_state(request.thread_id, waiting_for_identity=False)
                logger.debug(f"Cleared waiting_for_identity for thread_id {request.thread_id}")
        
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
        
    except Exception as e:
        logger.exception(f"Error processing ticket: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing ticket: {str(e)}"
        ) from e

