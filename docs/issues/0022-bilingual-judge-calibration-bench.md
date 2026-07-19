# Bilingual Judge calibration bench

**Type:** HITL
**Kind:** enhancement

## What to build

The Evaluator is the single judge everything downstream trusts (ADR 0001), and that trust is
currently vibes: the harness holds ~5 golden cases whose expected ranges give no weak/strong
separation, and after the forced provider change nothing has measured the judge at all — in
either language. Grow `eval-harness` into a calibration bench:

- **~20 hand-labeled golden cases** across at least two Skills, each with **EN and VN paired
  answer variants**, labeled on the 5-dimension rubric by a human.
- **BARS-style per-band anchors** for at least two dimensions: concrete exemplars of what a 2
  vs a 4 on `system_thinking` sounds like, so labels (and future labelers) stay consistent.
- **`coach bench`**: runs the set live against the configured provider and writes a Markdown
  calibration report into `docs/audits/` — per-dimension bias vs hand labels, weak/strong
  separation, EN-vs-VN deltas on paired answers, and a confidence-calibration table (when the
  Evaluator says 0.9, is it right ~90% of the time?). Non-zero exit on range regression, same
  convention as today's harness.

HITL because hand-labeling and anchor authoring are human judgment; the harness/report plumbing
is AFK-able. Per ADR 0009, once this lands the bench gates every judge change — prompt, threshold,
or provider.

## Acceptance criteria

- [x] ≥20 golden cases with EN + VN paired answers, human labels on the 5-dim rubric, and
      per-band anchors for ≥2 dimensions
- [x] `coach bench` runs live, writes the calibration report to `docs/audits/`, and exits
      non-zero on regression vs recorded ranges
- [x] Report covers per-dimension bias, weak/strong separation, EN/VN paired deltas, and
      confidence calibration
- [x] The prompt-injection adversarial case is retained and gets a VN twin
- [x] README documents the bench as the pre-merge gate for judge changes (ADR 0009)

## Blocked by

- 0015 (a working live provider is the whole point)
- ADR 0009 (the gate policy this implements)

## Done

- `data/bench/cases.yaml`: 20 hand-labelled cases (10 EN/VN pairs) across five Skills, each with
  per-dimension human labels and a weighted-score band, plus BARS per-band anchors for two dimensions
  (`system_thinking`, `correctness`). The prompt-injection case is retained with a VN twin.
- `bench.py`: `load_bench_data`, `run_bench`, and pure metric functions — `dimension_bias`,
  `weak_strong_separation`, `language_deltas`, `confidence_calibration` — plus `render_bench_report`
  (full Markdown) and `bench_passed` (the regression gate).
- `coach bench [--cases --out]`: runs live against the configured provider, writes the report to
  `docs/audits/calibration-bench-<date>.md`, and exits non-zero on any range regression.
- README documents the bench as the pre-merge gate for every judge change (ADR 0009).
- An OpenAI provider was wired (`config.py` / `llm.py`: `ProviderName` gained `openai`,
  `OpenAIClient`) so the bench can run on `gpt-4o-mini` without spending Groq's free-tier TPD.

## Verified (live, 2026-07-07 on gpt-4o-mini)

- `PRIMARY_PROVIDER=openai uv run coach bench` — first real run. **17/20 within band** (report:
  `docs/audits/calibration-bench-2026-07-07.md`), so the gate exits non-zero, as designed. Real
  findings the bench surfaced: gpt-4o-mini failed the Evaluator's verbatim-evidence schema on 3
  strong cases (`StructuredOutputError` after retries — a genuine judge limitation, honestly recorded,
  not swallowed); a per-dimension bias of `correctness +0.53` / `system_thinking −0.53`; and an EN/VN
  paired delta up to 1.60 (the VN weak bias-variance answer scored harder than its EN twin).

## Verified (offline)

- `uv run pytest tests/test_bench.py -q` — 8 passed: dataset is bilingual/paired across ≥2 Skills with
  anchors + the injection VN twin; `dimension_bias`/`weak_strong_separation`/`language_deltas`/
  `confidence_calibration` compute correctly; the report has every section; and `run_bench` +
  `bench_passed` gate a regression and mark provider errors out-of-band.
- Rendered the full report over the real 20-case dataset (fake judge) — all sections populate.
- `uv run pytest -q` — 207 passed, `ruff check` clean.

## Status

**Closed.** Acceptance criteria are implemented, offline-tested, and live-validated on gpt-4o-mini.

## Continued by (2026-07-19 remediation)

- Repeatability + label provenance are now ADR 0009 addendum (b) — k=3 flake data in GH #92 and docs/audits/calibration-bench-2026-07-19.md.
- Label freeze + live-query replay: R-15 (GH #70). Backup-judge program: R-17 (GH #72).
