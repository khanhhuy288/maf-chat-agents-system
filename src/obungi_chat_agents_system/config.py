from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    """Central configuration loaded from environment variables."""

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str
    azure_openai_deployment: str
    azure_openai_embedding_deployment: str
    ticket_logic_app_url: str
    default_response_language: str = "de"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        env = os.environ
        missing: list[str] = []
        values: dict[str, Any] = {}

        field_map = {
            "azure_openai_endpoint": "AZURE_OPENAI_ENDPOINT",
            "azure_openai_api_key": "AZURE_OPENAI_API_KEY",
            "azure_openai_api_version": "AZURE_OPENAI_API_VERSION",
            "azure_openai_deployment": "AZURE_OPENAI_DEPLOYMENT",
            "azure_openai_embedding_deployment": "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            "ticket_logic_app_url": "TICKET_LOGIC_APP_URL",
            "default_response_language": "DEFAULT_RESPONSE_LANGUAGE",
        }

        for attr, env_key in field_map.items():
            value = env.get(env_key)
            if value:
                values[attr] = value.strip()
            else:
                if attr == "default_response_language":
                    values[attr] = "de"
                    continue
                missing.append(env_key)

        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(**values)


settings = Settings.from_env()

