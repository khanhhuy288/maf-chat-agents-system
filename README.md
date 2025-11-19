
# Obungi Ticket Agent CLI

Agent-based IT ticket router powered by the Microsoft Agent Framework and Azure OpenAI.

## Getting Started

1. Install [uv](https://docs.astral.sh/uv/).
2. Copy `.env.example` to `.env` and fill in the Azure OpenAI + Logic App values.
3. Install dependencies: `uv sync --prerelease=allow`.

### Run the CLI

```
uv run --prerelease=allow obungi-chat-agents-system
```

1. Paste only the ticket text (finish with a blank line).
2. The workflow tries to extract `Name`, `Vorname`, and `E-Mail` automatically.
3. While the request is processed you’ll see live status updates (analysis, identity extraction, validation, routing) so it’s clear the workflow is running.
4. If anything is missing, the CLI highlights the missing fields and keeps asking until all are supplied, then prints the workflow response.

### Sample Cases

```
uv run --prerelease=allow python scripts/run_sample_cases.py
```

Runs representative prompts (per category plus an identity-missing scenario) in dispatcher simulation mode to validate the workflow end-to-end.

