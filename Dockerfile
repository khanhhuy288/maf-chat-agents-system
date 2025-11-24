# syntax=docker/dockerfile:1

# Dockerfile for DevUI - LOCAL DEVELOPMENT ONLY
# This is NOT for production use. DevUI is a development tool.
# For production, use Dockerfile.api instead.
#
# Multi-stage build for DevUI container
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim AS builder

# Prevents Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock* README.md ./

# Copy source code (needed for package build during uv sync)
COPY src/ ./src/

# Install dependencies using uv
RUN uv sync --frozen --no-dev || uv sync --frozen

# Final stage: minimal runtime image
FROM python:${PYTHON_VERSION}-slim

# Prevents Python from writing pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY src/ ./src/
COPY pyproject.toml ./

# Make sure we use the venv
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-privileged user
USER appuser

# Expose the port that the application listens on
EXPOSE 8080

# Health check - simple TCP check (DevUI may not have /health endpoint)
# Uncomment and customize if you add a health endpoint:
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 8080)); s.close()" || exit 1

# Run the DevUI server (LOCAL DEVELOPMENT ONLY)
CMD ["python", "-m", "chat_agents_system.devui_app", "--host", "0.0.0.0", "--port", "8080"]

