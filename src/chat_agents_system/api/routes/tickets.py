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
    Process a ticket through the multi-agent workflow system.
    
    ## Workflow Steps
    1. **Identity Extraction**: Extracts name, vorname, email from message or request fields
    2. **Validation**: Ensures all required identity fields are present
    3. **Classification**: Categorizes the request (AI history, O365, hardware, login, other)
    4. **Category Handling**: Routes to appropriate handler (Historian, Dispatcher, etc.)
    5. **Response**: Returns formatted response with status and message
    
    ## Two-Step Flow (Missing Identity)
    
    When identity information is missing, the endpoint supports a two-step conversation flow:
    
    **Step 1: Initial Request**
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "thread_id": "my-thread-123"
    }
    ```
    
    **Response:**
    ```json
    {
      "status": "missing_identity",
      "message": "Bitte geben Sie Ihre Angaben im Format Name, Vorname, E-Mail-Adresse an...",
      "metadata": {
        "thread_id": "my-thread-123",
        "missing_fields": ["name", "vorname", "email"],
        "missing_labels": ["Name", "Vorname", "E-Mail-Adresse"]
      }
    }
    ```
    
    **Step 2: Follow-up with Identity**
    ```json
    {
      "message": "Müller, Hans, hans@example.com",
      "thread_id": "my-thread-123"
    }
    ```
    
    The system automatically combines the original request with the identity information.
    
    ## Single Request (With Identity)
    
    You can also provide identity directly:
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "name": "Müller",
      "vorname": "Hans",
      "email": "hans@example.com"
    }
    ```
    
    ## Response Statuses
    
    - **completed**: Ticket processed successfully
    - **missing_identity**: Identity required (send follow-up with same thread_id)
    - **waiting_for_identity**: Still waiting for identity in correct format
    - **unsupported**: Request category not supported
    - **error**: Processing error occurred
    
    ## AI History Questions
    
    For questions about AI history (category: "Frage zur Historie von AI"), the `message` field
    contains the complete answer from the Historian agent. No additional processing is needed.
    
    ## Request Examples
    
    **Single Request with Identity:**
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "name": "Müller",
      "vorname": "Hans",
      "email": "hans@example.com",
      "thread_id": "thread-123",
      "simulate_dispatch": true
    }
    ```
    
    **Initial Request (Missing Identity):**
    ```json
    {
      "message": "Ich habe ein Problem mit meinem Login",
      "thread_id": "thread-123"
    }
    ```
    
    **Follow-up with Identity:**
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
        
        # Simplified state management: use thread_id for conversation continuity
        original_message: str | None = None
        prepared_message = request.message
        
        # If identity fields are provided directly, use them and skip state check
        if not (request.name or request.vorname or request.email) and request.thread_id:
            # Check if we're waiting for identity in this thread
            thread_state = get_thread_state(request.thread_id)
            
            if thread_state["waiting_for_identity"]:
                # Check if message matches identity format
                message_stripped = request.message.strip()
                if IDENTITY_FORMAT_PATTERN.match(message_stripped):
                    # This is identity information - combine with original message
                    original_message = thread_state["original_message"]
                    if original_message:
                        prepared_message = f"{original_message}\n\n---\n{request.message}"
                        logger.debug(f"Combining original message with identity info")
                    else:
                        logger.warning("State indicates waiting for identity but no original_message found")
                else:
                    # Still waiting for identity - return waiting status
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
        
        # Create workflow instance
        workflow = create_ticket_workflow(simulate_dispatch=request.simulate_dispatch)
        
        # Create ticket input with prepared message
        ticket_input = TicketInput(
            message=prepared_message,
            name=request.name,
            vorname=request.vorname,
            email=request.email,
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
                original_msg = original_message if original_message else prepared_message
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
        if result.status == "missing_identity" and original_message:
            response_metadata["original_message"] = original_message
            response_metadata["waiting_for_identity"] = True
        
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

