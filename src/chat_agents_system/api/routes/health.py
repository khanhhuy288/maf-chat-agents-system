"""Health check endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for Kubernetes/Docker probes."""
    return HealthResponse(
        status="healthy",
        service="chat-agents-system",
        version="1.0.0",
    )


@router.get("/ready")
async def readiness_check():
    """Readiness check endpoint - verifies dependencies are available."""
    # TODO: Add checks for Azure OpenAI connectivity if needed
    return {"status": "ready"}

