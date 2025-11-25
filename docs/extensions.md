# Frontend Integration & Extensions

## Table of contents

- [Frontend Integration](#frontend-integration)
  - [API surface](#api-surface)
  - [Minimal request](#minimal-request)
  - [Frontend musts](#frontend-musts)
  - [Environment & networking](#environment--networking)
- [Extension Ideas](#extension-ideas)

## Frontend Integration

### API surface

Base URL (local): `http://localhost:8000`

| Endpoint | Notes |
| --- | --- |
| `GET /health` | Liveness |
| `GET /ready` | Confirms Azure OpenAI + Logic App wiring |
| `GET /docs` / `/redoc` | Swagger / ReDoc |
| `POST /api/v1/tickets` | Runs intake → validation → classification → branch routing |

### Minimal request

```json
POST /api/v1/tickets
{
  "message": "Ich habe ein Problem mit meinem Login...",
  "thread_id": "thread-123"
}
```

Key statuses:

- `completed` → show confirmation, display historian text verbatim if `is_historian_answer` is true
- `missing_identity` or `waiting_for_identity` → prompt for `Name, Vorname, E-Mail-Adresse`, resend `original_message`
- `unsupported` → show fallback copy

### Frontend musts

- Generate and reuse a `thread_id`; without it the workflow treats follow-ups as new tickets.
- Cache the user’s first request so you can send it via `original_message` whenever identity is provided later.
- Validate identity input client-side (`Last, First, email@example.com`) and only call the API once all fields are present.
- Propagate HTTP failures to logs but show a generic retry message to users.

### Environment & networking

| Framework | Variable |
| --- | --- |
| React | `REACT_APP_API_URL` |
| Next.js (server) | `API_URL` |
| Vite/Vue | `VITE_API_URL` |

Match environments (local, staging, prod). When the frontend is hosted separately, configure FastAPI CORS accordingly:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
```

## Extension Ideas

1. **Observability** – structured logs, `/metrics`, tracing.
2. **Externalized state** – Redis conversation cache, PostgreSQL ticket log, optional vector store for historian RAG.
3. **Security + API hardening** – auth on `/api/v1/tickets`, rate limiting, audit logs.
4. **CI/CD & deployments** – GitHub Actions or Azure DevOps with tests, scans, ACA blue/green rollouts.
5. **Multi-channel intake** – Teams/Slack bots and email parsers standardizing inputs to `TicketInput`.
6. **Agent upgrades** – multi-language identity extraction, classification confidence scores, dispatcher retries.
7. **Analytics & testing** – dashboards, exports, load/chaos/A-B experiments.
