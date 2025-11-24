"""FastAPI application entry point for production API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from chat_agents_system.api.routes import health, tickets
from chat_agents_system.config import settings
from chat_agents_system.utils import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    logger.info("Starting Chat Agents System API")
    logger.info(f"Azure OpenAI Endpoint: {settings.azure_openai_endpoint}")
    logger.info(f"Default Language: {settings.default_response_language}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Chat Agents System API")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Chat Agents System API",
        description="Production REST API for ticket processing workflow",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(tickets.router, prefix="/api/v1", tags=["Tickets"])

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        """Global exception handler."""
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "message": str(exc) if logger.level == logging.DEBUG else "An error occurred",
            },
        )

    return app


# Create app instance
app = create_app()

