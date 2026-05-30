"""Runtime configuration, loaded from the environment / `.env`.

Issue 0004 makes the MiMo -> Groq cutover a ``PRIMARY_PROVIDER`` switch. Both providers are
OpenAI-compatible, but each has its own credentials/model so the cutover does not require editing
agent code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type ProviderName = Literal["mimo", "groq"]


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

    primary_provider: ProviderName = Field(
        "mimo",
        validation_alias=AliasChoices("PRIMARY_PROVIDER", "LLM_PRIMARY_PROVIDER", "LLM_PROVIDER"),
    )

    # MiMo keeps the old LLM_* aliases for backward compatibility with slice-0001/0005 .env files.
    mimo_api_key: str = Field("", validation_alias=AliasChoices("MIMO_API_KEY", "LLM_API_KEY"))
    mimo_base_url: str = Field("", validation_alias=AliasChoices("MIMO_BASE_URL", "LLM_BASE_URL"))
    mimo_model: str = Field("", validation_alias=AliasChoices("MIMO_MODEL", "LLM_MODEL"))

    groq_api_key: str = Field("", validation_alias=AliasChoices("GROQ_API_KEY", "LLM_GROQ_API_KEY"))
    groq_base_url: str = Field(
        "https://api.groq.com/openai/v1",
        validation_alias=AliasChoices("GROQ_BASE_URL", "LLM_GROQ_BASE_URL"),
    )
    groq_model: str = Field("", validation_alias=AliasChoices("GROQ_MODEL", "LLM_GROQ_MODEL"))

    temperature: float = Field(0.2, validation_alias=AliasChoices("LLM_TEMPERATURE"))
    timeout_seconds: float = Field(60.0, validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS"))

    @field_validator("primary_provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def fallback_provider(self) -> ProviderName:
        """The only other provider is the fallback for this MVP router."""
        return "groq" if self.primary_provider == "mimo" else "mimo"

    def provider_config(self, provider: ProviderName) -> ProviderSettings:
        """Return the normalized config for ``provider``."""
        if provider == "mimo":
            return ProviderSettings(
                name="mimo",
                api_key=self.mimo_api_key,
                base_url=self.mimo_base_url,
                model=self.mimo_model,
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
            )
        return ProviderSettings(
            name="groq",
            api_key=self.groq_api_key,
            base_url=self.groq_base_url,
            model=self.groq_model,
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
