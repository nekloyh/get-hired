"""Runtime configuration, loaded from the environment / `.env`.

Slice 0 keeps this to a single OpenAI-compatible connection (MiMo, the primary provider).
Multi-provider selection and failover (the ``PRIMARY_PROVIDER`` switch) arrive in issue 0004.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    provider: str = "mimo"
    temperature: float = 0.2
    timeout_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        """True once the connection is fully specified (enough to make a real call)."""
        return bool(self.api_key and self.base_url and self.model)


def load_settings() -> Settings:
    return Settings()
