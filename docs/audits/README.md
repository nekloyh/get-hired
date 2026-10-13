# Audits — dated records, and what each one measured

Every file here is a **record**: a measurement taken on a stated day, against the commit it names,
if it names one. No `coach bench` report does (`bench.render_bench_report` writes no commit);
the bench section below says how a report is tied to the judge it measured. From #140 on, a record is
not edited after its day; `git log --follow` shows edits made before then. When a later measurement
disagrees, it gets a new file and a new row here.
Records stay because a bench result proves that a change did or did not move a number, and deleting
one would make the next re-run impossible to check.

Nothing here is authoritative over an ADR. `docs/adr/0009` is the rule; these are its readings. And
nothing here is status. Work and its state live in the
[GitHub milestones](https://github.com/nekloyh/get-hired/milestones)
([rule](../issues/README.md#where-status-lives)).

## Judge calibration bench (ADR 0009)

The gate is **median-of-k, k=3, at production temperature** (ADR 0009 addendum b/d). One run is not
a measurement, and a band is never widened to turn a red green. The baseline for the judge the code builds
is whichever artifact [`judge.lock`](../../judge.lock) names (ADR 0009 addendum g). Every report from
#141 on carries a `Judge fingerprint` line, which is how it is tied to the exact judge it measured.

| Audit | Result | What it measured |
|---|---|---|
| [`calibration-bench-2026-09-15.md`](calibration-bench-2026-09-15.md) | **RED, 34/35** | the gate at `v0.1.0-pilot`. The red case is `vnlp_segmentation_weak_vi`, 2.70 against a 2.6 ceiling; its EN twin scores 2.20. That is the EN/VN split which the missing middle anchors in `depth` / `system_thinking` allow. The anchor work it calls for is [#96](https://github.com/nekloyh/get-hired/issues/96) |
| [`calibration-bench-2026-07-27-anchor96.md`](calibration-bench-2026-07-27-anchor96.md) | GREEN once, never confirmed | the **unmerged** first attempt at #96 (PR #104, archived). One green invocation of its final wording; an earlier wording went 35/35, 35/35, 34/35. The evidence behind ADR 0009 addenda (e) and (f) |
| [`calibration-bench-2026-07-27.md`](calibration-bench-2026-07-27.md) | GREEN, 35/35 | closed the 2026-07-19 AMBER gate (#92). Read it for the k=3 method |
| [`calibration-bench-2026-07-19.md`](calibration-bench-2026-07-19.md) | AMBER | the flake that produced #92 |
| [`calibration-bench-2026-07-11-*.md`](.) (10 files) | one per change | one for every change that touched the judge: gpt-5.4-mini cutover, re-anchor, json_schema, Panel Verdict, trust guards, bilingual mode, evidence-degrade, VN consistency (and its Groq cross-check), Panel baseline |
| [`calibration-bench-2026-07-07.md`](calibration-bench-2026-07-07.md) | first run | the first bench |

## Retrieval and content

| Audit | Result | What it measured |
|---|---|---|
| [`concept-retrieval-embedder-ab-2026-07-11.md`](concept-retrieval-embedder-ab-2026-07-11.md) | e5 wins VN | multilingual-e5 vs BGE on the real Chroma store |
| [`concept-retrieval-review-chroma-2026-07-11.md`](concept-retrieval-review-chroma-2026-07-11.md) | 46/50 | the real Chroma store with `bge-small-en-v1.5`; with the in-memory 47/50 and e5's 47/50, the numbers behind "the Skill filter does the work, not the embedder" |
| [`concept-retrieval-review-2026-07-11.md`](concept-retrieval-review-2026-07-11.md) | 47/50 | the same review on the in-memory store |
| [`question-bank-review-2026-07-11.md`](question-bank-review-2026-07-11.md) | — | bank breadth and difficulty labels at 42 questions |

## Audits, plans and milestones

| Record | What it is |
|---|---|
| [`pilot-plan-2026-10-13.md`](pilot-plan-2026-10-13.md) | a proposal, written after the maintainer re-ordered the priorities on 2026-10-13: what a trusted pilot meets at `2ceaf81`, three directions with costs, and the milestones, issues and tracker changes the chosen one needs; it binds only once the milestones exist on GitHub |
| [`docs-review-2026-10-12.md`](docs-review-2026-10-12.md) | the docs and ADR review at `2ceaf81`: 2,772 claims checked, 664 verified findings (46 high), in [`docs-review-2026-10-12.findings.jsonl`](docs-review-2026-10-12.findings.jsonl); its ADR recommendations are review input only, since ADR decisions were paused on 2026-10-13 |
| [`live-smoke-2026-10-12.md`](live-smoke-2026-10-12.md) | one live Session end-to-end on the compose stack at `830ddcf`: 26,478 tokens, 15 calls, accounting and trace attribution exact; run on dev keys, which fail pilot pre-flight line 1 (#139) |
| [`forensic-audit-2026-09-14.md`](forensic-audit-2026-09-14.md) | the forensic audit at `2dac711` plus the uncommitted M0a work; the input the QA report checked |
| [`qa-report-2026-09-15.md`](qa-report-2026-09-15.md) | QA of the stabilize branch: 47 findings, the M-0/M-1/M-2 task lists (`QA-NN`, `NEW-NN`, `M0-NN`, `M1-NN`, `M2-N`) |
| [`milestone-v0.1.0-pilot-2026-09-15.md`](milestone-v0.1.0-pilot-2026-09-15.md) | what `v0.1.0-pilot` shipped, the first full-stack nginx/TLS dry-run, and what that run found |
| [`implementation-plan-2026-09-13.md`](implementation-plan-2026-09-13.md) | the M0–M6 plan, its evidence contract and work IDs (`F1`, `Q1`, …); superseded as a *sequence* by the milestones |
| [`m0a-usage-ledger-2026-09-13.md`](m0a-usage-ledger-2026-09-13.md) | M0a: the usage ledger writes to the state volume and an accounting failure blocks metered calls |
| [`baseline-2026-09-02.md`](baseline-2026-09-02.md) | the Phase-1 fact sheet at `2dac711`, written before M-0/M-1 landed; check the code before quoting it |
| [`0015-groq-cutover-live-validation.md`](0015-groq-cutover-live-validation.md) | the Groq cutover. **MiMo is dead**: its free tokens expired 2026-06-03, and in this record its fallback fails 401. Its MiMo lines are history |
| [`0007-rag-interviewer-smoke.md`](0007-rag-interviewer-smoke.md) | the first tool-using Interviewer smoke run |

## Renamed on 2026-10-06

Records, commit messages and issue bodies cite the old names. These are the same files, unedited
apart from re-pointed relative links and the plan's new title and preface:

| Old name | Now |
|---|---|
| `AUDIT.md` | [`forensic-audit-2026-09-14.md`](forensic-audit-2026-09-14.md) |
| `QA-REPORT.md` | [`qa-report-2026-09-15.md`](qa-report-2026-09-15.md) |
| `MILESTONE-REPORT.md` | [`milestone-v0.1.0-pilot-2026-09-15.md`](milestone-v0.1.0-pilot-2026-09-15.md) |
| `docs/issues/README.md`, below its status section | [`implementation-plan-2026-09-13.md`](implementation-plan-2026-09-13.md) |

## Research inputs (`../research/`)

Not records of measurements: reading passes over primary sources, accessed 2026-09-02, and two
reports (in Vietnamese) built on them and on the [baseline](baseline-2026-09-02.md). A price or
library fact in them is true as of that access date.

| File | What it is |
|---|---|
| [`2026-09-02-market-landscape.md`](../research/2026-09-02-market-landscape.md) | interview-prep products, global and Vietnamese, and the employer-side AI interviewers candidates face |
| [`2026-09-02-oss-landscape.md`](../research/2026-09-02-oss-landscape.md) | open-source mock-interview and interview-coach projects, read from their repositories |
| [`2026-09-02-stack-references.md`](../research/2026-09-02-stack-references.md) | stack facts (orchestration, models and pricing, voice, persistence, deployment), no recommendations |
| [`report-1-features-2026-09-02.md`](../research/report-1-features-2026-09-02.md) | Report 1: which features to build next, scored against the project's priority order |
| [`report-2-architecture-2026-09-02.md`](../research/report-2-architecture-2026-09-02.md) | Report 2: the stack and architecture for the next form of the product |

## Where the live answers are

- **What it cannot do yet**: the *Known limits* table in [`../../README.md`](../../README.md), each row linking its issue where one exists.
- **What must be true before real people use it**: [`../pilot-runbook.md`](../pilot-runbook.md).
- **What is being built, and in what order**: the [GitHub milestones](https://github.com/nekloyh/get-hired/milestones).
