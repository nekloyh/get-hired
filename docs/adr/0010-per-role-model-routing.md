# Per-role model routing and decoding parameters

**Status: Accepted (2026-07-19).** Implementation tracked as R-18 (GH #73); until it lands, the
current single-config router is the documented interim state, not a competing decision.

Each agent **role** — `judge` (Evaluator), `interviewer`, `supervisor`, `diagnostic`, `planner` —
maps to its own provider/model **and its own decoding parameters** (temperature, and any future
sampling knobs) via env configuration. Defaults reproduce today's behavior exactly (zero-change
rollout, guarded by a regression test that the default config produces byte-identical
prompts/models). The `judge` role is special-cased by ADR 0009's addendum: pinned to a
bench-validated model, failover never swaps it. No role gains tools by this ADR (ADR 0003's
per-need rule is untouched).

## Why

One router config currently serves every agent, which welds together two decisions that have
opposite requirements and were never actually made:

- **Model choice.** The judge needs the most *accurate* model (every score flows into the Beta
  state, ADR 0009); the Interviewer needs cheap + fast + tool-capable; seed rendering needs
  almost nothing. Verified 2026-07-19 pricing puts hybrid routing at roughly **$87 per 1000
  sessions vs $176 all-on-judge-model** — the cost lever and the judge-pinning lever are the same
  mechanism.
- **Decoding.** A single global `LLM_TEMPERATURE=0.2` (`config.py:56`) throttles the
  Interviewer's question variety and simultaneously makes the *gate* stochastic — the k=3 bench
  flake documented in ADR 0009(b) is partly this one shared knob. Judge determinism and
  interviewer creativity must not share a dial.

Both were implicit decisions living only in code (`config.py:56`, and the hardcoded fallback
preference order at `config.py:69`); this ADR makes them explicit and per-role.

## Considered Options

- **Keep the single router config** (status quo): rejected — it makes judge pinning (ADR 0009a)
  inexpressible and prices every role at judge-model rates.
- **Per-agent client classes** (each agent constructs its own provider client): rejected —
  routing is configuration, not code structure; per-agent clients re-scatter what `LLMRouter`
  centralizes and violate the "no agent imports a provider client" rule.
- **Dynamic per-call model selection by an LLM** ("model-picker agent"): rejected — adds a
  judgment call to every call, unauditable, and the roles' needs are static.

*Source: remediation decision B1 (routing table + verified pricing, 2026-07-19); ADR red-team
review 2026-07-19 — implicit decisions #2 (global temperature) and #3 (fallback order) folded in.*
