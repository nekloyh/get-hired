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

- [ ] `.env` matches the documented scheme; a live `coach session --scripted --max-questions 1`
      completes on Groq end-to-end (micro-loop, follow-up tool call, Study Plan, export)
- [ ] `uv run pytest -m live` passes against Groq with the tests actually *executing* — a run
      where they all skip on missing credentials counts as failure for this criterion
- [ ] A `docs/audits/` entry records the first Groq validation: date, model, which tests ran,
      any behavioral deltas vs the MiMo-era notes (tool-name flakiness, `reasoning_content`)
- [ ] The legacy `LLM_*` alias path is either documented or removed — it can no longer silently
      select an unconfigured/dead provider while the documented vars are absent
- [ ] README setup instructions match the final scheme

## Blocked by

None — can start immediately. Everything live-dependent (0022, 0029) is blocked on this.

## Status

**Open.**
