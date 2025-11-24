
# Ticket Agent System

Showcase of a Microsoft Agent Framework workflow that turns free-form German IT helpdesk messages into routed tickets. The system combines Azure OpenAI reasoning, identity extraction, category-specific handling, and Logic App dispatch—all while remaining fully local-dev friendly.

## Features
- Multi-agent workflow purpose-built for ticket intake and routing
- Microsoft Agent Framework Dev UI with conversational agent support
- Strong focus on identity validation, guardrails, and deterministic dispatching
- Production-style integrations (Azure OpenAI, Logic Apps) with simulation switches for demos

## Agent Lineup & Responsibilities
| Agent | Purpose | Key Skills |
| --- | --- | --- |
| `IdentityExtractorExecutor` | Entry point that normalizes input, keeps the original request, and extracts `Name`, `Vorname`, `E-Mail` via Azure OpenAI plus regex fallback. | Intake + extraction, LLM parsing |
| `ValidationExecutor` | Halts the workflow until all identity fields are present, returning a single strict format request for the Dev UI to relay. | Guardrails, UX loops |
| `ClassificationExecutor` | Categorizes the ticket into five buckets, emits a ≤9-word summary, and produces a cleaned request body for downstream consumers. | LLM reasoning, content structuring |
| `HistorianExecutor` | Generates concise German answers when the ticket is “Frage zur Historie von AI,” feeding the dispatcher/formatter pipeline. | Domain-specific response crafting |
| `DispatcherExecutor` | Builds the structured payload and (optionally) posts it to the Logic App; simulation mode mirrors the final success text. | Integrations, HTTP |
| `ResponseFormatterExecutor` | Consolidates the final human response plus lightweight metadata/payloads; short-circuits OTHER tickets with an `unsupported` status. | Presentation, metadata packaging |

## Workflow at a Glance
1. **User submits raw text only.** No forms—just paste the full request.
2. **Agents collaborate sequentially.** Each executor enriches a shared `TicketContext` dataclass.
3. **Identity-first guardrails.** Missing attributes trigger a friendly clarification message; clients re-run with the required fields.
4. **Branching after classification.** The workflow branches into three paths based on category:
   - **AI_HISTORY**: classification → historian (generates answer) → dispatcher → formatter
   - **O365/HARDWARE/LOGIN**: classification → dispatcher → formatter (skips historian)
   - **OTHER**: classification → formatter (early exit, skips both historian and dispatcher)
5. **Consistent responses.** The formatter returns the answer, classification, and dispatch payload so any client (Dev UI, tests) can display the same result.

## Getting Started
1. Install [uv](https://docs.astral.sh/uv/).
2. Copy `.env.example` to `.env`, set Azure OpenAI + Logic App values.
3. Install dependencies: `uv sync --prerelease=allow`.

### Local Development (DevUI)

**⚠️ DevUI is for LOCAL DEVELOPMENT ONLY, not production!**

![Workflow input form](2025-11-19_15-43-39.png)
![Dev UI execution timeline](2025-11-19_15-19-31.png)

```bash
uv run --prerelease=allow chat-agents-system-devui --auto-open
```
- Registers the "Ticket Workflow" inside the Microsoft Agent Framework Dev UI.
- Lets reviewers inspect each agent step, streamed responses, and dispatcher payloads.
- By default, dispatch is simulated (no actual POST requests are sent). Use `--enable-dispatch` to send real requests to the Logic App.

### Production API (FastAPI)

```bash
# Run production API server
uv run --prerelease=allow chat-agents-system-api

# Or with custom port
uv run --prerelease=allow chat-agents-system-api --port 8000
```

- Production-ready REST API at `http://localhost:8000`
- Interactive API docs at `http://localhost:8000/docs`
- Health check at `http://localhost:8000/health`

### Sample Cases (scripted demo)
```bash
uv run --prerelease=allow python scripts/run_sample_cases.py
```
Runs representative prompts (all categories plus identity edge cases) with dispatch simulation—ideal for regression tests or CI.

## Tech Stack
- **Framework:** Microsoft Agent Framework (planner-free sequential workflow)
- **LLM:** Azure OpenAI Chat (classification, historian, identity reasoning)
- **Runtime:** `uv` for dependency + script management
- **Integrations:** Azure Logic Apps (JSON webhook dispatch)
- **Language:** Python 3.11+

## Project Structure
```
src/chat_agents_system/
├─ agents/                 # Individual executors (intake, identity, validation, etc.)
├─ api/                    # Production FastAPI REST API
│  ├─ main.py             # FastAPI application
│  └─ routes/             # API route handlers
├─ workflow.py             # Sequential workflow wiring each agent
├─ devui_app.py            # Dev UI server (LOCAL DEVELOPMENT ONLY)
├─ api_server.py           # Production API server entry point
└─ schemas.py              # TicketContext + response dataclasses
```

## Deployment

### Docker

- **DevUI (Local Development)**: See [DOCKER.md](DOCKER.md) for local development setup
- **Production API**: Use `Dockerfile.api` for production deployments

### Azure Container Apps

Deploy to Azure Container Apps for serverless container hosting with automatic scaling: See [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md)

### Frontend Integration

Connect your frontend to the production API: See [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md)

## Extension Ideas

See [EXTENSION_IDEAS.md](EXTENSION_IDEAS.md) for additional enhancement ideas:
- Observability & monitoring
- State management & persistence
- CI/CD pipelines
- Multi-channel intake
- Enhanced agent capabilities

Use this repo to demonstrate real-world agent orchestration, integration-ready prompts, and a complete ticketing pipeline. 

