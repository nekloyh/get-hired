# Self-critique reflection

> **Superseded:** the lone re-read this slice built was replaced by the Panel Verdict (slice 0027, GH #28, PR #47). The triggers survive (`evaluator._self_critique_triggers`), but a triggered judgment now escalates to a Skeptic and an Advocate (`evaluator._panel_opinion`) and an Evaluator re-judgment that has read both, and `evaluator.evaluate` keeps that verdict unconditionally, whatever its confidence. Read `docs/issues/0027-panel-verdict.md` for the design that replaced it.

**Type:** AFK

## What to build

The evaluator-optimizer reflection step (see `ADR 0001`): **Self-critique** lives inside the Evaluator's micro-loop, not the Supervisor. When an evaluation's `confidence` is below threshold — including the low-confidence signal raised by the `weighted_score` cross-check guard (slice 0003) — re-evaluate the same exchange (e.g. with a critique of the first pass appended) and keep the more confident result. This produces a trustworthy score for the current question before control ever returns to the macro-loop.

> **Superseded:** since slice 0027 (PR #47) the re-evaluation is a Panel Verdict, not a re-read with a critique appended: `evaluator._panel_opinion` runs a Skeptic and an Advocate, the Evaluator re-judges with both opinions in its prompt (`evaluator._build_panel_verdict_messages`), and `evaluator.evaluate` keeps that verdict even when it is less confident than the first pass (`tests/test_evaluator.py::test_panel_verdict_is_kept_even_when_less_confident_than_the_first_pass`). The panel advises; the Evaluator decides (ADR 0001).

## Acceptance criteria

### Implemented

- [x] A low-confidence evaluation triggers exactly one re-evaluation pass

  > **Superseded:** a triggered evaluation now escalates to one Panel Verdict: two advisory `evaluator._panel_opinion` calls, then exactly one Evaluator re-evaluation (slice 0027, PR #47). `microloop.run_micro_loop` gives each question one `evaluator.PanelBudget.per_question()`; when it is spent, or a panel voice fails, the guarded first pass is kept and `evaluator.TrustTrace.panel_suppressed` is set.

- [x] A high-confidence evaluation does not trigger re-evaluation
- [x] The cross-check divergence from slice 0003 is one of the triggers
- [x] The result kept is the higher-confidence of the two passes, and the trigger + outcome are logged

  > **Superseded:** the kept result is the Panel Verdict, unconditionally, not the higher-confidence pass (slice 0027, PR #47). The triggers and the first-pass score and confidence are logged and recorded in `evaluator.PanelTrace`.

- [x] Micro-loop transcript trace exposes the self-critique triggers for the turn that was judged

### Verified live

- [x] MiMo live Evaluator sanity check passes (`uv run pytest -m live -ra`, verified 2026-05-31)

## Blocked by

- 0005 (operates within the micro-loop)

## Status

**Closed.** Acceptance criteria are implemented and covered.

## Continued by (2026-07-19 remediation)

- The low-confidence trigger is measurably dormant on gpt-5.4-mini (saturation ≥0.90) → deterministic trigger set is R-16 (GH #71); the replacement signal is ADR 0011 (Proposed, gated E4/E5).
