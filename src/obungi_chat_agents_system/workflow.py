from __future__ import annotations

from agent_framework import Workflow, WorkflowBuilder
from agent_framework.azure import AzureOpenAIChatClient

from obungi_chat_agents_system.agents import (
    ClassificationExecutor,
    DispatcherExecutor,
    HistorianExecutor,
    IdentityExtractorExecutor,
    IntakeExecutor,
    ResponseFormatterExecutor,
    ValidationExecutor,
)
from obungi_chat_agents_system.config import settings


def create_chat_client() -> AzureOpenAIChatClient:
    return AzureOpenAIChatClient(
        api_key=settings.azure_openai_api_key,
        endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        deployment_name=settings.azure_openai_deployment,
    )


def create_ticket_workflow(*, dry_run_dispatch: bool = False) -> Workflow:
    chat_client = create_chat_client()

    intake = IntakeExecutor()
    identity = IdentityExtractorExecutor(chat_client)
    validation = ValidationExecutor()
    classification = ClassificationExecutor(chat_client)
    historian = HistorianExecutor(chat_client)
    dispatcher = DispatcherExecutor(
        settings.ticket_logic_app_url, simulate_only=dry_run_dispatch
    )
    formatter = ResponseFormatterExecutor()

    workflow = (
        WorkflowBuilder()
        .set_start_executor(intake)
        .add_edge(intake, identity)
        .add_edge(identity, validation)
        .add_edge(validation, classification)
        .add_edge(classification, historian)
        .add_edge(historian, dispatcher)
        .add_edge(dispatcher, formatter)
        .build()
    )

    return workflow

