"""Runtime configuration, loaded from the environment / `.env`.

Issue 0004 makes the MiMo -> Groq cutover a ``PRIMARY_PROVIDER`` switch. Both providers are
OpenAI-compatible, but each has its own credentials/model so the cutover does not require editing
agent code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type ProviderName = Literal["mimo", "groq", "openai"]


class ProviderSettings(BaseModel):
    """Connection details for one OpenAI-compatible provider."""

    name: ProviderName
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: float = 60.0

    @property
    def configured(self) -> bool:
        """True once the provider has enough configuration to make a real call."""
        return bool(self.api_key and self.base_url and self.model)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    primary_provider: ProviderName = Field("mimo", validation_alias="PRIMARY_PROVIDER")

    mimo_api_key: str = Field("", validation_alias="MIMO_API_KEY")
    mimo_base_url: str = Field("", validation_alias="MIMO_BASE_URL")
    mimo_model: str = Field("", validation_alias="MIMO_MODEL")

    groq_api_key: str = Field("", validation_alias="GROQ_API_KEY")
    groq_base_url: str = Field("https://api.groq.com/openai/v1", validation_alias="GROQ_BASE_URL")
    groq_model: str = Field("", validation_alias="GROQ_MODEL")

    openai_api_key: str = Field("", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field("https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field("", validation_alias="OPENAI_MODEL")

    temperature: float = Field(0.2, validation_alias="LLM_TEMPERATURE")
    timeout_seconds: float = Field(60.0, validation_alias="LLM_TIMEOUT_SECONDS")

    @field_validator("primary_provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def fallback_provider(self) -> ProviderName:
        """The first other provider in preference order is the fallback for this MVP router."""
        for candidate in ("groq", "mimo", "openai"):
            if candidate != self.primary_provider:
                return candidate
        return "mimo"

    def provider_config(self, provider: ProviderName) -> ProviderSettings:
        """Return the normalized config for ``provider``."""
        creds: dict[ProviderName, tuple[str, str, str]] = {
            "mimo": (self.mimo_api_key, self.mimo_base_url, self.mimo_model),
            "groq": (self.groq_api_key, self.groq_base_url, self.groq_model),
            "openai": (self.openai_api_key, self.openai_base_url, self.openai_model),
        }
        api_key, base_url, model = creds[provider]
        return ProviderSettings(
            name=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )

    @property
    def primary_config(self) -> ProviderSettings:
        return self.provider_config(self.primary_provider)

    @property
    def fallback_config(self) -> ProviderSettings:
        return self.provider_config(self.fallback_provider)

    @property
    def configured(self) -> bool:
        """True once the selected primary provider can make a real call."""
        return self.primary_config.configured


def load_settings() -> Settings:
    return Settings()
