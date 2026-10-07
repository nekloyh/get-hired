# Audits — dated records, and what each one measured

Every file here is a **record**: a measurement taken on a stated day against a stated commit. It is
never edited after that day. When a later measurement disagrees, it gets a new file and a new row here.
Records stay because a bench result proves that a change did or did not move a number, and deleting
one would make the next re-run impossible to check.

Nothing here is authoritative over an ADR. `docs/adr/0009` is the rule; these are its readings. And
nothing here is status. Work and its state live in the
[GitHub milestones](https://github.com/nekloyh/get-hired/milestones)
([rule](../issues/README.md#where-status-lives)).

## Judge calibration bench (ADR 0009)

The gate is **median-of-k, k=3, at production temperature** (ADR 0009 addendum b/d). One run is not
a measurement, and a band is never widened to turn a red green. The newest dated artifact is the
current reading.

| Audit | Result | What it measured |
|---|---|---|
| [`calibration-bench-2026-09-15.md`](calibration-bench-2026-09-15.md) | **RED, 34/35** | the gate at `v0.1.0-pilot`. The red case is `vnlp_segmentation_weak_vi`, 2.70 against a 2.6 ceiling; its EN twin scores 2.20. That is the EN/VN split which the missing middle anchors in `depth` / `system_thinking` allow. Owned by [#96](https://github.com/nekloyh/get-hired/issues/96) |
| [`calibration-bench-2026-07-27.md`](calibration-bench-2026-07-27.md) | GREEN, 35/35 | closed the 2026-07-19 AMBER gate (#92). Read it for the k=3 method |
| [`calibration-bench-2026-07-19.md`](calibration-bench-2026-07-19.md) | AMBER | the flake that produced #92 |
| [`calibration-bench-2026-07-11-*.md`](.) (11 files) | one per change | one for every change that touched the judge: gpt-5.4-mini cutover, re-anchor, json_schema, Panel Verdict, trust guards, bilingual mode, evidence-degrade, VN consistency (and its Groq cross-check), Panel baseline |
| [`calibration-bench-2026-07-07.md`](calibration-bench-2026-07-07.md) | first run | the first bench |

## Retrieval and content

| Audit | Result | What it measured |
|---|---|---|
| [`concept-retrieval-embedder-ab-2026-07-11.md`](concept-retrieval-embedder-ab-2026-07-11.md) | e5 wins VN | multilingual-e5 vs BGE on the real Chroma store |
| [`concept-retrieval-review-chroma-2026-07-11.md`](concept-retrieval-review-chroma-2026-07-11.md) | 47/50 | the real store; the number behind "the Skill filter does the work, not the embedder" |
| [`concept-retrieval-review-2026-07-11.md`](concept-retrieval-review-2026-07-11.md) | — | the same review on the in-memory store |
| [`question-bank-review-2026-07-11.md`](question-bank-review-2026-07-11.md) | — | bank breadth and difficulty labels at 42 questions |

## Audits, plans and milestones

| Record | What it is |
|---|---|
| [`forensic-audit-2026-09-14.md`](forensic-audit-2026-09-14.md) | the forensic audit at `2dac711` plus the uncommitted M0a work; the input the QA report checked |
| [`qa-report-2026-09-15.md`](qa-report-2026-09-15.md) | QA of the stabilize branch: 47 findings, the M-0/M-1/M-2 task lists (`QA-NN`, `M0-NN`, `M1-NN`, `M2-N`) |
| [`milestone-v0.1.0-pilot-2026-09-15.md`](milestone-v0.1.0-pilot-2026-09-15.md) | what `v0.1.0-pilot` shipped, the first full-stack nginx/TLS dry-run, and what that run found |
| [`implementation-plan-2026-09-13.md`](implementation-plan-2026-09-13.md) | the M0–M6 plan, its evidence contract and work IDs (`F1`, `Q1`, …); superseded as a *sequence* by the milestones |
| [`m0a-usage-ledger-2026-09-13.md`](m0a-usage-ledger-2026-09-13.md) | M0a: the ledger writes to the state volume and an accounting failure blocks metered calls |
| [`baseline-2026-09-02.md`](baseline-2026-09-02.md) | the Phase-1 fact sheet at `2dac711`, written before M-0/M-1 landed; check the code before quoting it |
| [`0015-groq-cutover-live-validation.md`](0015-groq-cutover-live-validation.md) | the Groq cutover. **MiMo is dead** (endpoint retired 2026-06-03); its MiMo lines are history |
| [`0007-rag-interviewer-smoke.md`](0007-rag-interviewer-smoke.md) | the first tool-using Interviewer smoke run |

## Renamed on 2026-10-06

Records, commit messages and issue bodies cite the old names. These are the same files, unedited
apart from re-pointed relative links:

| Old name | Now |
|---|---|
| `AUDIT.md` | [`forensic-audit-2026-09-14.md`](forensic-audit-2026-09-14.md) |
| `QA-REPORT.md` | [`qa-report-2026-09-15.md`](qa-report-2026-09-15.md) |
| `MILESTONE-REPORT.md` | [`milestone-v0.1.0-pilot-2026-09-15.md`](milestone-v0.1.0-pilot-2026-09-15.md) |
| `docs/issues/README.md`, below its status section | [`implementation-plan-2026-09-13.md`](implementation-plan-2026-09-13.md) |

## Where the live answers are

- **What it cannot do yet**: the *Known limits* table in [`../../README.md`](../../README.md), each row linking its issue.
- **What must be true before real people use it**: [`../pilot-runbook.md`](../pilot-runbook.md).
- **What is being built, and in what order**: the [GitHub milestones](https://github.com/nekloyh/get-hired/milestones).
