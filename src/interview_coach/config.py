"""Runtime configuration, loaded from the environment / `.env`.

Issue 0004 makes the MiMo -> Groq cutover a ``PRIMARY_PROVIDER`` switch. Both providers are
OpenAI-compatible, but each has its own credentials/model so the cutover does not require editing
agent code.

Per-role routing (ADR 0010, issue R-18): each agent role — ``judge``, ``interviewer``,
``supervisor``, ``diagnostic``, ``planner`` — may override its provider, model, and temperature via
``ROLE_<ROLE>_PROVIDER`` / ``_MODEL`` / ``_TEMPERATURE``. Unset roles inherit today's single-router
behavior exactly (zero-change rollout). Changing the judge role's provider/model/temperature is a
judge change and is gated by ``coach bench`` (ADR 0009).
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type ProviderName = Literal["mimo", "groq", "openai"]

type RoleName = Literal["judge", "interviewer", "supervisor", "diagnostic", "planner"]

ROLE_NAMES: tuple[RoleName, ...] = get_args(RoleName.__value__)


class ProviderSettings(BaseModel):
    """Connection details for one OpenAI-compatible provider.

    ``supports_json_schema`` is capability config, not a class trait: a provider entry binds ONE
    model at a time, so an instance-level override is effectively per-model. ``None`` defers to the
    client class's verified default (only OpenAI's is live-probed True today).
    """

    name: ProviderName
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout_seconds: float = 60.0
    supports_json_schema: bool | None = None

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

    # Per-provider capability override (per-model in effect — a provider entry binds one model).
    # None = defer to the client class's live-verified default.
    mimo_supports_json_schema: bool | None = Field(None, validation_alias="MIMO_SUPPORTS_JSON_SCHEMA")
    groq_supports_json_schema: bool | None = Field(None, validation_alias="GROQ_SUPPORTS_JSON_SCHEMA")
    openai_supports_json_schema: bool | None = Field(None, validation_alias="OPENAI_SUPPORTS_JSON_SCHEMA")

    temperature: float = Field(0.2, validation_alias="LLM_TEMPERATURE")
    timeout_seconds: float = Field(60.0, validation_alias="LLM_TIMEOUT_SECONDS")

    # ADR 0010: per-role overrides. Empty/None = inherit the primary provider / provider model /
    # global temperature — the pre-0010 behavior, byte-identical.
    role_judge_provider: str = Field("", validation_alias="ROLE_JUDGE_PROVIDER")
    role_judge_model: str = Field("", validation_alias="ROLE_JUDGE_MODEL")
    role_judge_temperature: float | None = Field(None, validation_alias="ROLE_JUDGE_TEMPERATURE")
    role_interviewer_provider: str = Field("", validation_alias="ROLE_INTERVIEWER_PROVIDER")
    role_interviewer_model: str = Field("", validation_alias="ROLE_INTERVIEWER_MODEL")
    role_interviewer_temperature: float | None = Field(None, validation_alias="ROLE_INTERVIEWER_TEMPERATURE")
    role_supervisor_provider: str = Field("", validation_alias="ROLE_SUPERVISOR_PROVIDER")
    role_supervisor_model: str = Field("", validation_alias="ROLE_SUPERVISOR_MODEL")
    role_supervisor_temperature: float | None = Field(None, validation_alias="ROLE_SUPERVISOR_TEMPERATURE")
    role_diagnostic_provider: str = Field("", validation_alias="ROLE_DIAGNOSTIC_PROVIDER")
    role_diagnostic_model: str = Field("", validation_alias="ROLE_DIAGNOSTIC_MODEL")
    role_diagnostic_temperature: float | None = Field(None, validation_alias="ROLE_DIAGNOSTIC_TEMPERATURE")
    role_planner_provider: str = Field("", validation_alias="ROLE_PLANNER_PROVIDER")
    role_planner_model: str = Field("", validation_alias="ROLE_PLANNER_MODEL")
    role_planner_temperature: float | None = Field(None, validation_alias="ROLE_PLANNER_TEMPERATURE")

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
        json_schema_overrides: dict[ProviderName, bool | None] = {
            "mimo": self.mimo_supports_json_schema,
            "groq": self.groq_supports_json_schema,
            "openai": self.openai_supports_json_schema,
        }
        return ProviderSettings(
            name=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
            supports_json_schema=json_schema_overrides[provider],
        )

    def role_overridden(self, role: RoleName) -> bool:
        """Whether any ROLE_* env override exists for ``role``."""
        provider, model, temperature = self._role_fields(role)
        return bool(provider) or bool(model) or temperature is not None

    def role_config(self, role: RoleName) -> ProviderSettings:
        """The provider config ``role`` resolves to, with its overrides applied.

        Fails loudly on an unknown provider name — a typo must not silently route a role to the
        primary (same principle as ``validate_language_mode``).
        """
        provider_raw, model, temperature = self._role_fields(role)
        provider = provider_raw.strip().lower() or self.primary_provider
        if provider not in ("mimo", "groq", "openai"):
            raise ValueError(
                f"ROLE_{role.upper()}_PROVIDER={provider_raw!r} is not a known provider; "
                "expected one of ('mimo', 'groq', 'openai')"
            )
        config = self.provider_config(provider)  # type: ignore[arg-type]
        return config.model_copy(
            update={
                "model": model or config.model,
                "temperature": temperature if temperature is not None else config.temperature,
            }
        )

    def _role_fields(self, role: RoleName) -> tuple[str, str, float | None]:
        return (
            getattr(self, f"role_{role}_provider"),
            getattr(self, f"role_{role}_model"),
            getattr(self, f"role_{role}_temperature"),
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
