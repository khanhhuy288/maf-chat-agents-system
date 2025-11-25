# 🧪 Testing & CI Guide

Essential steps to validate the Ticket Agent System. Keep tests fast, deterministic, and aligned with the documented architecture.

## 📋 Table of contents
- [Manual smoke tests](#manual-smoke-tests)
- [Automated tests](#automated-tests)
- [CI basics](#ci-basics)
- [Troubleshooting](#troubleshooting)

## 💨 Manual smoke tests

1. Start the API: `uv run --prerelease=allow chat-agents-system-api`
2. Open `http://localhost:8000/docs` and call `POST /api/v1/tickets`
3. Send the free-form request: `{"message":"Ich habe ein Problem mit meinem Login","thread_id":"manual-thread"}`
   - Expect `status: "missing_identity"`
4. Resend only identity: `{"message":"Schneider, Peter, peter@example.com","thread_id":"manual-thread"}`
   - Expect `status: "completed"` (or `unsupported`)

Quick curl loop:

```bash
curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{"message":"Ich habe ein Problem","thread_id":"curl-demo"}'

curl -X POST http://localhost:8000/api/v1/tickets \
  -H "Content-Type: application/json" \
  -d '{"message":"Schneider, Peter, peter@example.com","thread_id":"curl-demo"}'
```

Extra scenarios to sanity-check:
- Identity embedded in natural language (`"mein Name ist …"`)
- Partial identity (should return `missing_identity` metadata)
- AI history request (historian answer forwarded)
- Unsupported request (formatter returns `status:"unsupported"`)

## 🤖 Automated tests

```bash
uv sync --prerelease=allow
uv run --prerelease=allow pytest tests/ -v
```

- Uses FastAPI `TestClient`; no server process needed.
- Stubs Azure OpenAI + Logic App calls.
- Verifies identity loops, strict format enforcement, `thread_id` handling, and successful dispatch simulation.

Sample cases runner (forces simulated dispatch):

```bash
uv run --prerelease=allow python scripts/run_sample_cases.py
```

## 🔄 CI basics

Minimal pipeline:
1. Checkout
2. `uv sync --prerelease=allow`
3. `pytest tests/ -v`
4. `docker build -f Dockerfile.api ...`
5. Push/deploy as desired

GitHub Actions starter:

```yaml
name: ci
on:
  push:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --prerelease=allow
      - run: pytest tests/ -v
```

## 🔧 Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tests need Azure secrets | `.env` missing | Export env vars or set CI secrets |
| Stuck in `waiting_for_identity` | Follow-up not in `Name, Vorname, E-Mail` format | Send exact comma-separated identity |
| HTTP 500 in tests | Bad dispatcher URL / `.env` | Use fake URL + simulation |
| Flaky extraction | Randomized prompts | Mock executor; rely on deterministic fixtures |
