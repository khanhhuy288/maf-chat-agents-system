"""Ticket processing endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chat_agents_system.schemas import TicketInput, TicketResponse
from chat_agents_system.utils import get_logger
from chat_agents_system.workflow import (
    create_ticket_workflow,
    prepare_ticket_message,
    update_identity_state,
)

logger = get_logger(__name__)
router = APIRouter()


class TicketRequest(BaseModel):
    """Request model for ticket processing."""

    message: str = Field(..., description="The user's ticket message")
    name: str | None = Field(None, description="User's last name (optional)")
    vorname: str | None = Field(None, description="User's first name (optional)")
    email: str | None = Field(None, description="User's email address (optional)")
    thread_id: str | None = Field(
        None, description="Thread ID for conversation continuity (optional)"
    )
    simulate_dispatch: bool = Field(
        True, description="Whether to simulate dispatch (default: True)"
    )


class TicketResponseModel(BaseModel):
    """Response model for ticket processing."""

    status: str = Field(..., description="Processing status")
    message: str = Field(..., description="Response message")
    payload: dict[str, Any] | None = Field(None, description="Dispatch payload if applicable")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


@router.post("/tickets", response_model=TicketResponseModel)
async def process_ticket(request: TicketRequest) -> TicketResponseModel:
    """Process a ticket through the workflow system.
    
    This endpoint accepts a ticket message and processes it through the multi-agent
    workflow system, which includes:
    - Identity extraction
    - Validation
    - Classification
    - Category-specific handling (AI history, O365, hardware, login, other)
    - Dispatch to Logic App (if applicable)
    
    The endpoint supports conversation continuity via thread_id. When identity information
    is missing, the endpoint will return a 'missing_identity' status. On the next request
    with the same thread_id, if the message matches the identity format (e.g., 
    "Müller, Hans, hans@example.com"), it will be automatically combined with the 
    original request.
    
    Args:
        request: Ticket request containing message and optional identity fields
        
    Returns:
        TicketResponseModel with processing status, message, and metadata.
        The metadata will include 'thread_id' if provided, allowing clients to
        maintain conversation continuity.
        
    Raises:
        HTTPException: If processing fails
    """
    try:
        logger.info(f"Processing ticket request: message={request.message[:100]}...")
        
        # Prepare message with state management (handles follow-up identity messages)
        prepared_message, msg_metadata = prepare_ticket_message(
            message=request.message,
            thread_id=request.thread_id,
            name=request.name,
            vorname=request.vorname,
            email=request.email,
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
        
        # Update state based on result (similar to conversational agent)
        if request.thread_id or msg_metadata.get("is_follow_up"):
            update_identity_state(
                status=result.status,
                thread_id=request.thread_id,
                original_message=msg_metadata.get("original_message"),
                prepared_message=prepared_message,
            )
        
        logger.info(f"Ticket processed successfully: status={result.status}")
        
        # Build response metadata
        response_metadata = result.metadata or {}
        if request.thread_id:
            response_metadata["thread_id"] = request.thread_id
        if msg_metadata.get("waiting_for_identity"):
            response_metadata["waiting_for_identity"] = True
            if msg_metadata.get("original_message"):
                response_metadata["original_message"] = msg_metadata["original_message"]
        
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

