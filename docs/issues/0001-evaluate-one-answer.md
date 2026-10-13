# Evaluate one answer

**Type:** AFK

## What to build

The thinnest end-to-end judgment path: take one hard-coded question and a fixture Candidate answer, call the **Evaluator** (a single LLM call via structured-output `chat_json`), and print a typed evaluation. The rubric uses the fixed 5-dimension vocabulary (correctness, depth, communication, system_thinking, mlops_awareness) with per-question weights, where weight 0 disables a dimension. The Evaluator emits per-dimension scores (1–5) with verbatim evidence, an LLM-emitted `weighted_score`, a `confidence`, and `follow_up_recommended`. No skill-state, no loop, no RAG yet — just answer in, structured judgment out.

> **Superseded:** `rubric.DIMENSIONS` now has a sixth dimension, `english_delivery` (issue 0024, ADR 0007, PR #46). The five above are `rubric.TECHNICAL_DIMENSIONS`, and only they feed `weighted_score` (`rubric.Rubric.active_technical`, `evaluator.linear_weighted_score`); `language.rubric_with_delivery` turns `english_delivery` on or off per answer.

The `follow_up_recommended` flag is the Evaluator's own judgment framed around *marginal information gain* ("would a follow-up likely reveal something not already known?"), not a score threshold.

## Acceptance criteria

- [x] Running the slice on a fixture Q+answer prints a valid, schema-validated evaluation object

  > **Superseded:** the printing demo was `coach evaluate`, deleted in 4f8cdf3 (PR #133); see the note under Done.

- [x] Per-dimension scores carry verbatim evidence quotes from the answer (or an explicit "no evidence")
- [x] Dimensions with weight 0 are not scored
- [x] A clearly weak answer yields low scores; a strong fixture answer yields high scores
- [x] Structured-output parsing retries once on validation failure before erroring

  > **Superseded:** the judge call now retries validation up to `evaluator.JUDGE_MAX_RETRIES` times (PR #89); other callers keep the `llm.LLMClient.chat_json` default of one retry. When only the verbatim-evidence check (`evaluator.EvidenceViolation`) exhausts its retries, `evaluator._evaluate_once` makes one more `chat_json` round without that check and blanks the unverifiable citations (`evaluator._sanitize_unverifiable_evidence`) instead of erroring (e198250, PR #34). Any other exhausted failure still raises `llm.StructuredOutputError`.

## Blocked by

None - can start immediately.

## Done

Implemented by `src/interview_coach/evaluator.py`, fixture content in `src/interview_coach/fixtures.py`,
and the `coach evaluate` CLI path. Covered by `tests/test_evaluator.py`, including schema validation,
retry behavior, verbatim evidence enforcement, disabled dimensions, and live weak-vs-strong scoring.

> **Superseded:** `coach evaluate` was deleted in 4f8cdf3 (PR #133). The Evaluator now runs on every turn of a Session (`microloop.run_micro_loop` calls `evaluator.evaluate`); `coach bench` and `coach eval-harness` run it on fixed, labelled answers; and `tests/test_evaluator.py` still exercises `evaluator.evaluate` on `fixtures.QUESTION`, `fixtures.STRONG_ANSWER` and `fixtures.WEAK_ANSWER`.

## Status

**Closed.** Acceptance criteria are implemented and covered.
