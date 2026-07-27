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

type ProviderName = Literal["mimo", "groq", "openai", "zenmux"]

type RoleName = Literal["judge", "interviewer", "supervisor", "diagnostic", "planner"]

ROLE_NAMES: tuple[RoleName, ...] = get_args(RoleName.__value__)
PROVIDER_NAMES: tuple[ProviderName, ...] = get_args(ProviderName.__value__)

# Providers with a green `coach bench` artifact in docs/audits/ — the only ones allowed to hold the
# judge role (ADR 0009 addendum a). Everything else is an *availability* tier: fine for the
# Interviewer, the Supervisor, or a planner, and disqualified from scoring.
#
# Groq is the worked example of why this is a set and not a comment: `llama-3.3-70b` scores 18/20
# with a VN over-scoring delta of 2.00, so a Session that quietly judged on it would produce numbers
# that look exactly like the validated ones. ZenMux joins on the same terms — a bench artifact, not
# a plausible-sounding model name.
BENCH_VALIDATED_JUDGE_PROVIDERS: frozenset[str] = frozenset({"openai"})


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

    # ZenMux: an OpenAI-compatible aggregator, added as an *availability* tier only. It has no bench
    # artifact, so it is not in BENCH_VALIDATED_JUDGE_PROVIDERS and cannot hold the judge role.
    zenmux_api_key: str = Field("", validation_alias="ZENMUX_API_KEY")
    zenmux_base_url: str = Field("https://zenmux.ai/api/v1", validation_alias="ZENMUX_BASE_URL")
    zenmux_model: str = Field("", validation_alias="ZENMUX_MODEL")

    # Per-provider capability override (per-model in effect — a provider entry binds one model).
    # None = defer to the client class's live-verified default.
    mimo_supports_json_schema: bool | None = Field(None, validation_alias="MIMO_SUPPORTS_JSON_SCHEMA")
    groq_supports_json_schema: bool | None = Field(None, validation_alias="GROQ_SUPPORTS_JSON_SCHEMA")
    openai_supports_json_schema: bool | None = Field(None, validation_alias="OPENAI_SUPPORTS_JSON_SCHEMA")
    zenmux_supports_json_schema: bool | None = Field(None, validation_alias="ZENMUX_SUPPORTS_JSON_SCHEMA")

    # Explicit, auditable escape hatch for running the judge on a provider with no bench artifact.
    # The ADR's objection is to a *silent* swap, so refusing by default and demanding an env var the
    # operator had to type keeps the decision visible in the deployment rather than in a stack trace.
    allow_unvalidated_judge: bool = Field(False, validation_alias="COACH_ALLOW_UNVALIDATED_JUDGE")

    temperature: float = Field(0.2, validation_alias="LLM_TEMPERATURE")
    timeout_seconds: float = Field(60.0, validation_alias="LLM_TIMEOUT_SECONDS")

    # Web gate (R-07). A single shared secret for the ≤50-user deployment this project targets;
    # real per-user auth is R-29. UNSET MEANS OPEN, which is the right default for `localhost` dev
    # and the wrong one the moment this is exposed — hence the startup warning in ``create_app``.
    auth_token: str = Field("", validation_alias="COACH_AUTH_TOKEN")
    # Comma-separated browser origins allowed to open a Session socket. One source of truth for both
    # CORS and the WebSocket Origin check: CORSMiddleware never sees a WS handshake, so a
    # browser-origin policy that lives only in CORS does not actually guard the socket.
    allowed_origins: str = Field("", validation_alias="COACH_ALLOWED_ORIGINS")

    # Where the server keeps state that must outlive the process (R-11). The defaults are the
    # historical CWD-relative paths, so nothing changes for a local run; a container points all
    # three at one mounted volume, which is what makes `docker restart` mid-question resumable.
    checkpoint_db: str = Field(".session-checkpoints.sqlite", validation_alias="COACH_CHECKPOINT_DB")
    ledger_db: str = Field(".skill-ledger.json", validation_alias="COACH_LEDGER_DB")
    exports_dir: str = Field("data/exports", validation_alias="COACH_EXPORTS_DIR")
    # Built React bundle to serve from this app. Empty = API only (the dev-server setup, where Vite
    # serves the UI). Set in the image so one container answers both the UI and the API on one
    # origin — which is also what lets the bundle default to same-origin instead of baking a host.
    static_dir: str = Field("", validation_alias="COACH_STATIC_DIR")
    # How long a finished Session's checkpoint thread is kept before the startup sweep drops it
    # (R-27). Long enough that reconnecting to a just-finished Session still replays its report;
    # short enough that the SQLite file does not grow for the life of the deployment. 0 disables.
    checkpoint_ttl_seconds: float = Field(7 * 24 * 3600, validation_alias="COACH_CHECKPOINT_TTL_SECONDS")

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
        """The first other provider in preference order is the fallback for this MVP router.

        ``zenmux`` sits last on purpose: one of the first three is always different from the primary,
        so appending it cannot change the fallback any existing configuration resolves to.
        """
        for candidate in ("groq", "mimo", "openai", "zenmux"):
            if candidate != self.primary_provider:
                return candidate
        return "mimo"

    def provider_config(self, provider: ProviderName) -> ProviderSettings:
        """Return the normalized config for ``provider``."""
        creds: dict[ProviderName, tuple[str, str, str]] = {
            "mimo": (self.mimo_api_key, self.mimo_base_url, self.mimo_model),
            "groq": (self.groq_api_key, self.groq_base_url, self.groq_model),
            "openai": (self.openai_api_key, self.openai_base_url, self.openai_model),
            "zenmux": (self.zenmux_api_key, self.zenmux_base_url, self.zenmux_model),
        }
        api_key, base_url, model = creds[provider]
        json_schema_overrides: dict[ProviderName, bool | None] = {
            "mimo": self.mimo_supports_json_schema,
            "groq": self.groq_supports_json_schema,
            "openai": self.openai_supports_json_schema,
            "zenmux": self.zenmux_supports_json_schema,
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
        if provider not in PROVIDER_NAMES:
            raise ValueError(
                f"ROLE_{role.upper()}_PROVIDER={provider_raw!r} is not a known provider; "
                f"expected one of {PROVIDER_NAMES}"
            )
        if role == "judge":
            self._require_bench_validated_judge(provider, provider_raw)
        config = self.provider_config(provider)  # type: ignore[arg-type]
        return config.model_copy(
            update={
                "model": model or config.model,
                "temperature": temperature if temperature is not None else config.temperature,
            }
        )

    def _require_bench_validated_judge(self, provider: str, provider_raw: str) -> None:
        """Refuse to seat the judge on a provider with no green bench artifact (ADR 0009a).

        The ADR pins the judge because every score flows into the Beta state, the Supervisor's
        deviation calls, and the Study Plan — a judge nobody measured produces numbers indistinguishable
        from measured ones. Groq is the standing example: 18/20 with a VN over-scoring delta of 2.00.

        This is a *configuration* guard, distinct from the runtime pinning in ``build_role_clients``
        (which stops failover from swapping the judge mid-Session). Both are needed: one closes the
        env-var path, the other the outage path.
        """
        if provider in BENCH_VALIDATED_JUDGE_PROVIDERS or self.allow_unvalidated_judge:
            return
        source = f"ROLE_JUDGE_PROVIDER={provider_raw!r}" if provider_raw.strip() else f"PRIMARY_PROVIDER={provider!r}"
        raise ValueError(
            f"{source} would put the judge role on a provider with no green `coach bench` artifact. "
            f"ADR 0009 pins the judge to a bench-validated model; validated today: "
            f"{sorted(BENCH_VALIDATED_JUDGE_PROVIDERS)}. Either set ROLE_JUDGE_PROVIDER to one of "
            f"those, or bench the new provider (`uv run coach bench --k 3`), commit the report to "
            f"docs/audits/ and add it to BENCH_VALIDATED_JUDGE_PROVIDERS. To run knowingly on an "
            f"unvalidated judge — scores are NOT comparable to bench-validated ones — set "
            f"COACH_ALLOW_UNVALIDATED_JUDGE=1."
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
