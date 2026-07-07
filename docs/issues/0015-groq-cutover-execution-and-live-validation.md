# Groq cutover execution + first live validation

**Type:** AFK
**Kind:** bug

## What to build

Issue 0004 built the cutover *mechanism*; the cutover itself never happened. The real `.env` still
carries only the legacy `LLM_*` variables, which the settings loader aliases exclusively to MiMo —
whose free tokens expired 2026-06-03 — and no `GROQ_*` credentials exist, so `LLMRouter` has
nothing to fail over to. Confirmed by the 2026-07 stability audit: **every live path
(`coach session` live, `coach diagnose`, web live mode) currently fails with no fallback**, and
every recorded live verification in the repo is MiMo-era. Groq has never been validated once —
its tool-call emission and JSON discipline differ from both MiMo and the offline fakes.

Execute the cutover end-to-end: bring `.env` onto the documented scheme
(`PRIMARY_PROVIDER=groq` + `GROQ_*` per `.env.example`), run the live suite against Groq, and
record the result as an audit. Decide the fate of the legacy `LLM_*` alias path in the settings
loader — either document it in `.env.example`/README or remove it; today it exists only in code
and silently steered the live path onto a dead provider.

## Acceptance criteria

- [x] `.env` matches the documented scheme; a live `coach session --scripted --max-questions 1`
      completes on Groq end-to-end (micro-loop, follow-up tool call, Study Plan, export)
- [x] `uv run pytest -m live` passes against Groq with the tests actually *executing* — a run
      where they all skip on missing credentials counts as failure for this criterion
- [x] A `docs/audits/` entry records the first Groq validation: date, model, which tests ran,
      any behavioral deltas vs the MiMo-era notes (tool-name flakiness, `reasoning_content`)
- [x] The legacy `LLM_*` alias path is either documented or removed — it can no longer silently
      select an unconfigured/dead provider while the documented vars are absent
- [x] README setup instructions match the final scheme

## Blocked by

None — can start immediately. Everything live-dependent (0022, 0029) is blocked on this.

## Done

- `.env` migrated from the legacy `LLM_PROVIDER`/`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` scheme to
  `PRIMARY_PROVIDER`/`MIMO_*`/`GROQ_*` (the `.env.example`/README scheme). `GROQ_MODEL` had never
  been set — `GROQ_API_KEY` alone was a silent no-op.
- `GROQ_MODEL=llama-3.3-70b-versatile` chosen after comparing free-tier rate limits with
  `llama-3.1-8b-instant` and `openai/gpt-oss-120b` (highest TPM of the three despite being the
  largest model).
- Removed the legacy `LLM_*` alias `validation_alias` entries from `config.py` — this was the exact
  mechanism that let `.env` silently stay on expired MiMo while `GROQ_API_KEY` looked configured.
  No test depended on the aliases; README/`.env.example` never documented them.
- Also live re-validated issues 0016/0018/0019/0020, which had only ever been closed on
  fake/simulated evidence, and filed issue 0030 for a new gap found in the process (the CLI's
  Diagnostic-phase call has no transport-error backstop, unlike the three graph node call sites).

## Verified

- `uv run python scripts/smoke_issue_0009.py` — real Groq call, schema-valid Topic Plans.
- `uv run pytest -m live` — 5 passed, 0 skipped, first-ever non-MiMo run of this suite.
- `uv run pytest -q` — 165 passed, ruff clean, after the `config.py` alias removal.
- Full detail, including the live re-validation of 0016/0018/0019/0020 and the rate-limit/process-
  group findings along the way, in `docs/audits/0015-groq-cutover-live-validation.md`.

## Status

**Closed.** Acceptance criteria are implemented and covered.
