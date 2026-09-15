# Audits — which of these is a current answer, and which is a record

Twenty-two files with no index is a directory where the newest and the oldest look identical. Each
audit is a measurement taken on a stated day against a stated commit, and **only the rows marked
CURRENT answer a question about the code as it is now.** Everything else is a record of what was
true then: kept because a bench result is evidence that a change did or did not move a number, and
deleting it would make the next re-run unfalsifiable.

Nothing here is authoritative over an ADR. `docs/adr/0009` is the rule; these are its readings.

## Judge calibration bench (ADR 0009)

The gate is **median-of-k, k=3, at production temperature** (ADR 0009 addendum b/d). One run is not
a measurement, and a band is never widened to turn a red green.

| Audit | State | What it measured |
|---|---|---|
| [`calibration-bench-2026-09-15.md`](calibration-bench-2026-09-15.md) | **CURRENT — RED, 34/35** | the gate at `v0.1.0-pilot`. The failing case is the EN/VN split on `depth` / `system_thinking`, both of which have a gap at 3 in their 1–5 scale. Owned by [#96](https://github.com/nekloyh/get-hired/issues/96) |
| [`calibration-bench-2026-07-27.md`](calibration-bench-2026-07-27.md) | superseded — was GREEN 35/35 | closed the 2026-07-19 AMBER gate (#92). Read it for the k=3 method, not for today's number |
| [`calibration-bench-2026-07-19.md`](calibration-bench-2026-07-19.md) | record — AMBER | the flake that produced #92 |
| [`calibration-bench-2026-07-11-*.md`](.) (11 files) | record | one per change that touched the judge: gpt-5.4-mini cutover, re-anchor, json_schema, Panel Verdict, trust guards, bilingual mode, evidence-degrade, VN consistency (and its Groq cross-check), Panel baseline |
| [`calibration-bench-2026-07-07.md`](calibration-bench-2026-07-07.md) | record | the first bench |

## Retrieval and content

| Audit | State | What it measured |
|---|---|---|
| [`concept-retrieval-embedder-ab-2026-07-11.md`](concept-retrieval-embedder-ab-2026-07-11.md) | record | multilingual-e5 vs BGE on the real Chroma store |
| [`concept-retrieval-review-chroma-2026-07-11.md`](concept-retrieval-review-chroma-2026-07-11.md) | record | 47/50 on the real store — the number behind "the Skill filter does the work, not the embedder" |
| [`concept-retrieval-review-2026-07-11.md`](concept-retrieval-review-2026-07-11.md) | record | the same review on the in-memory store |
| [`question-bank-review-2026-07-11.md`](question-bank-review-2026-07-11.md) | record | bank breadth and difficulty labels at 42 questions |

## Slices and milestones

| Audit | State | What it measured |
|---|---|---|
| [`m0a-usage-ledger-2026-09-13.md`](m0a-usage-ledger-2026-09-13.md) | record | M0a: the ledger writes to the state volume and an accounting failure blocks metered calls |
| [`baseline-2026-09-02.md`](baseline-2026-09-02.md) | record, partly stale | the Phase-1 fact sheet at `2dac711`. Written before M-0/M-1 landed, so its gaps are the plan they became — check the code before quoting it |
| [`0015-groq-cutover-live-validation.md`](0015-groq-cutover-live-validation.md) | record | the Groq cutover. **MiMo is dead** (endpoint retired 2026-06-03); this file's MiMo lines are history |
| [`0007-rag-interviewer-smoke.md`](0007-rag-interviewer-smoke.md) | record | the first tool-using Interviewer smoke run |

## Where the current answers actually live

- **What the deployment is and what it cannot do** — [`../../MILESTONE-REPORT.md`](../../MILESTONE-REPORT.md)
- **What must be true before real people use it** — [`../pilot-runbook.md`](../pilot-runbook.md)
- **What is being built next** — [`../issues/README.md`](../issues/README.md)
