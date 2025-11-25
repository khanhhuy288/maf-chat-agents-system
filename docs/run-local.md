# 🏃 Run the Ticket Workflow Locally

Two local entry points ship with the Microsoft Agent Framework project:

- **DevUI** for interactive inspection of each executor step
- **FastAPI** for exercising the production REST surface

Prefer containers? See `docs/run-docker.md`.

## 📑 Table of contents

- [Prerequisites](#prerequisites)
- [DevUI (local demo)](#devui-local-demo)
- [FastAPI (local API)](#fastapi-local-api)
- [Helpful scripts](#helpful-scripts)
- [Troubleshooting](#troubleshooting)

## ✅ Prerequisites

- Python 3.11+ (3.12 works) and [`uv`](https://docs.astral.sh/uv/)
- `.env` populated from `.env.example`:
  - Azure OpenAI endpoint, key, API version, chat + embedding deployments
  - `TICKET_LOGIC_APP_URL`
  - Optional `DEFAULT_RESPONSE_LANGUAGE` (defaults to `de`)

Install dependencies once:

```bash
uv sync --prerelease=allow
```

## 🎨 DevUI (local demo)

```bash
uv run --prerelease=allow chat-agents-system-devui --auto-open
```

- Launches the DevUI catalog on `http://localhost:8080`
- Registers the Ticket Workflow + conversational agent
- Dispatcher stays in simulation; pass `--enable-dispatch` only when you want to hit the Logic App
- Restart the `uv run` process after editing `src/`

## 🚀 FastAPI (local API)

```bash
# default port 8000
uv run --prerelease=allow chat-agents-system-api
# custom port
uv run --prerelease=allow chat-agents-system-api --port 9000
```

- Mirrors the cloud REST contract with auto-reload
- Forces simulated dispatch for safety
- Maintains identity loops when you reuse `thread_id`
- Swagger/ReDoc live at `/docs` and `/redoc`; health endpoints `/health` and `/ready`

Quick identity loop:

```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{"message":"Ich habe ein Problem mit meinem Login","thread_id":"demo"}'

curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{"message":"Schneider, Peter, peter@example.com","thread_id":"demo"}'
```

## 🛠️ Helpful scripts

- `uv run --prerelease=allow python scripts/run_sample_cases.py`
- `pytest tests/ -v`
- `pytest tests/test_api_tickets.py::test_missing_identity_two_step_flow`

## 🔧 Troubleshooting

| Issue | Fix |
| --- | --- |
| Port in use | Pick another `--port` or free it with `lsof -i :8000` |
| Env vars missing | Re-copy `.env.example` and export values into your shell |
| Identity loop stuck | Send `Name, Vorname, E-Mail-Adresse` with the same `thread_id` |
| API 500 | Check terminal logs; most failures stem from missing Azure config |

Need Docker parity, CI recipes, or cloud deployment? Continue with `docs/run-docker.md`, `docs/testing-ci.md`, or `docs/cloud-deploy.md`.


