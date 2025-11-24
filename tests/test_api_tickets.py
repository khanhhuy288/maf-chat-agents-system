import os

import pytest
from fastapi.testclient import TestClient

# Provide required configuration before importing the app.
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_API_VERSION", "2024-06-01")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-test")
os.environ.setdefault("TICKET_LOGIC_APP_URL", "https://logic-app.invalid")
os.environ.setdefault("DEFAULT_RESPONSE_LANGUAGE", "de")

from chat_agents_system.api.main import create_app
from chat_agents_system import workflow as workflow_module
from chat_agents_system.schemas import TicketResponse


class _FakeEvents:
    def __init__(self, outputs: list[TicketResponse]):
        self._outputs = outputs

    def get_outputs(self) -> list[TicketResponse]:
        return self._outputs


class _FakeWorkflow:
    """Collects the last TicketInput and returns pre-defined responses."""

    def __init__(self, outputs: list[TicketResponse]):
        self.outputs = outputs
        self.inputs = []

    async def run(self, ticket_input):
        self.inputs.append(ticket_input)
        return _FakeEvents(self.outputs)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_identity_state():
    workflow_module._identity_state.clear()
    workflow_module._identity_state_by_message.clear()
    yield
    workflow_module._identity_state.clear()
    workflow_module._identity_state_by_message.clear()


@pytest.fixture
def workflow_stub(monkeypatch):
    """Patch the workflow factory to return a controllable fake."""

    def _stub(*responses: TicketResponse) -> _FakeWorkflow:
        fake = _FakeWorkflow(list(responses))

        def _factory(simulate_dispatch: bool = True):
            return fake

        monkeypatch.setattr(workflow_module, "create_ticket_workflow", _factory)
        return fake

    return _stub


def test_missing_identity_two_step_flow(client, workflow_stub):
    thread_id = "thread-123"
    initial_message = "Ich habe ein Problem mit meinem Login"

    workflow_stub(
        TicketResponse(
            status="missing_identity",
            message="Bitte ergänzen Sie Ihre Identität.",
            metadata={"missing_fields": ["name", "vorname", "email"]},
        )
    )

    response = client.post(
        "/api/v1/tickets",
        json={"message": initial_message, "thread_id": thread_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "missing_identity"
    assert data["metadata"]["thread_id"] == thread_id

    workflow_state = workflow_module.get_thread_state(thread_id)
    assert workflow_state["waiting_for_identity"] is True
    assert workflow_state["original_message"] == initial_message

    fake = workflow_stub(
        TicketResponse(
            status="completed",
            message="Ticket abgeschlossen.",
            metadata={"category": "Probleme bei der Anmeldung"},
            payload={"name": "Müller", "vorname": "Hans", "email": "hans@example.com"},
        )
    )

    identity_message = "Müller, Hans, hans@example.com"
    response = client.post(
        "/api/v1/tickets",
        json={"message": identity_message, "thread_id": thread_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["metadata"]["thread_id"] == thread_id

    # The workflow should receive the original message for the second step.
    assert fake.inputs[0].original_message == initial_message

    workflow_state = workflow_module.get_thread_state(thread_id)
    assert workflow_state["waiting_for_identity"] is False


def test_waiting_for_identity_blocks_non_identity_messages(client, workflow_stub, monkeypatch):
    thread_id = "thread-wait"

    workflow_stub(
        TicketResponse(
            status="missing_identity",
            message="Identität notwendig.",
            metadata={"missing_fields": ["email"]},
        )
    )
    response = client.post(
        "/api/v1/tickets",
        json={"message": "Bitte helft mir", "thread_id": thread_id},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "missing_identity"

    def _fail_factory(*_args, **_kwargs):
        raise AssertionError("Workflow should not run while waiting for identity.")

    monkeypatch.setattr(workflow_module, "create_ticket_workflow", _fail_factory)

    response = client.post(
        "/api/v1/tickets",
        json={"message": "Dies ist keine Identität", "thread_id": thread_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "waiting_for_identity"
    assert data["metadata"]["waiting_for_identity"] is True

    workflow_stub(
        TicketResponse(
            status="completed",
            message="Ticket abgeschlossen.",
            metadata={},
        )
    )
    response = client.post(
        "/api/v1/tickets",
        json={"message": "Müller, Hans, hans@example.com", "thread_id": thread_id},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_identity_follow_up_without_thread_id_is_rejected(client, monkeypatch):
    def _fail_factory(*_args, **_kwargs):
        raise AssertionError("Workflow should not run without thread_id.")

    monkeypatch.setattr(workflow_module, "create_ticket_workflow", _fail_factory)

    response = client.post(
        "/api/v1/tickets",
        json={"message": "Müller, Hans, hans@example.com"},
    )
    assert response.status_code == 400
    assert "thread_id" in response.json()["detail"]


def test_single_request_with_identity_fields(client, workflow_stub):
    fake = workflow_stub(
        TicketResponse(
            status="completed",
            message="Dispatcher simuliert.",
            metadata={"category": "Probleme bei der Anmeldung"},
            payload={"name": "Müller"},
        )
    )
    payload = {
        "message": "Ich habe ein Problem mit Outlook",
        "name": "Müller",
        "vorname": "Hans",
        "email": "hans@example.com",
        "simulate_dispatch": False,
    }
    response = client.post("/api/v1/tickets", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["payload"]["name"] == "Müller"

    # Ensure payload passed through to the workflow.
    ticket_input = fake.inputs[0]
    assert ticket_input.name == "Müller"
    assert ticket_input.vorname == "Hans"
    assert ticket_input.email == "hans@example.com"

