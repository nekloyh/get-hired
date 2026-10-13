# Provider router + cutover rehearsal

> **Superseded:** MiMo, `MimoClient` and the thinking-mode plumbing were removed in 3f19c99 (PR #133). `config.ProviderName` is `groq | openai | zenmux`, served by `llm.GroqClient`, `llm.OpenAIClient` and `llm.ZenMuxClient`; the judge role is pinned and never routed (ADR 0009 addendum a, ADR 0010). Everything below about MiMo is the 2026-05 design.

**Type:** AFK

## What to build

The provider abstraction that makes the planned MiMo→Groq cutover a one-env-var change. Introduce an `LLMClient` ABC with `chat` and `chat_json`, a MiMo client (quarantining the `reasoning_content` thinking-mode quirk — see `ADR 0003`), a Groq client, and an `LLMRouter` that selects the primary by env var and fails over to the fallback on error. Refactor slice 0001's direct call to go through the router; no agent may import a provider client directly.

This is pulled early on purpose: MiMo free tokens expire **2026-06-03**, so the swap must be rehearsed and tested well before the deadline, not discovered on it.

## Acceptance criteria

- [x] All LLM calls go through `LLMRouter`; no direct provider imports in agent code

  > **Superseded:** agents still depend only on `llm.LLMClient` and import no provider client, but not every call is routed. `llm.build_role_clients` gives the judge, and any role with a `ROLE_*` override, a pinned single-provider client (`llm._pinned_role_client`) that never fails over; the other roles share the `llm.LLMRouter` from `llm.build_client` (PR #95, ADR 0010, ADR 0009 addendum a).

- [x] `PRIMARY_PROVIDER` env var switches MiMo ↔ Groq with no other code change

  > **Superseded:** `PRIMARY_PROVIDER` selects among `config.ProviderName` with no code change, but the judge follows it only onto a (provider, model, base_url) in `config.BENCH_VALIDATED_JUDGES`. Otherwise `config.Settings._require_bench_validated_judge` refuses to seat the judge unless `ROLE_JUDGE_PROVIDER` / `ROLE_JUDGE_MODEL` name a validated triple or `COACH_ALLOW_UNVALIDATED_JUDGE` is set (PR #105, ADR 0009 addendum a).

- [x] Router fails over to the fallback provider on a primary error

  > **Superseded:** failover is typed (R-09, #64, PR #98). `llm.LLMRouter` fails over only when `llm.is_provider_failure` holds (`openai.APIError`, `llm.EmptyCompletionError`, and since PR #133 `usage.ProviderQuotaExhausted`); our own errors and `llm.ToolCallingUnsupported` propagate. A per-provider circuit breaker (`llm.BREAKER_FAILURE_THRESHOLD`, `llm.LLMRouter.breaker_is_open`) routes straight to a configured fallback while the primary is tripped. The fallback is the single provider named by `config.Settings.fallback_provider`.

- [x] A test runs the *same* prompt through both MiMo and Groq and validates both parse into the same schema
- [x] The MiMo `reasoning_content`/thinking-mode handling lives only inside the MiMo client

## Blocked by

- 0001 (generalizes its concrete LLM call)

## Done

`LLMClient` is now an ABC with raw `chat` plus shared structured-output `chat_json` parsing/retry.
`MimoClient` and `GroqClient` are OpenAI-compatible provider clients; MiMo's
`reasoning_content` handling remains quarantined in `MimoClient`. `LLMRouter` selects
`PRIMARY_PROVIDER` (`mimo` or `groq`) and falls back to the other configured provider when the
primary chat call errors. `build_client(load_settings())` is the CLI construction path; test
fixtures also route agent calls through `LLMRouter`, so agent modules keep depending on `LLMClient`
rather than provider clients. Covered by `tests/test_llm.py`; `.env.example` documents
provider-specific credentials.

> **Superseded:** `MimoClient` was removed in 3f19c99 (PR #133); the clients are `llm.GroqClient`, `llm.OpenAIClient` and `llm.ZenMuxClient` (`llm._CLIENT_CLASSES`). `PRIMARY_PROVIDER` takes `groq`, `openai` or `zenmux`, and the router falls back only on a provider failure, to the one provider `config.Settings.fallback_provider` names, when that provider is configured (`llm.LLMRouter._usable_fallback`). The judge never goes through the router (`llm.build_role_clients`, PR #95).

## Status

**Closed.** Acceptance criteria are implemented and covered.
