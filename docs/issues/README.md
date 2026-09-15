# Implementation plan — quality-gated vertical slices

## Status and authority

**Planned; no implementation started by this update. Updated 2026-09-13.** This is the canonical
sequencing and milestone index for `docs/issues/`; numbered slice documents retain their detailed
contracts and historical completion records. It replaces the old Now/Next/Later ordering only
where the reconciliation table below says so. Accepted ADRs still win. GitHub Issues remain the
live work tracker; links here reuse existing work, not newly created issues.

Code inspection baseline: `2dac711b3b9efc292406222e369fcd0a45301872` in the local checkout.
No runtime configuration, code, issues, commits, or live eval campaigns changed in this planning
pass. GitHub issue/PR status was **not refreshed**: linked identifiers are existing references,
not assertions that work is still open or that a remote branch has landed. Before implementation,
check the linked issue and any pending PR, reuse their work, and record the actual starting commit.

## Goals, scope, and assumptions

Priority stays **(1) learn agentic systems, (2) a usable interview-preparation tool,
(3) recruiter signal**. Learning outcomes are concrete: durable agent state and side effects,
measured judge quality, replayable control decisions, then evidence of useful repeat practice.

Scope: stabilize the existing text Session; make feedback trustworthy and debuggable; complete
Interview → feedback → practice again → inspect progress; prepare a separately gated public path.
Keep FastAPI/React, the Python Micro-loop, LangGraph Macro-loop, single Evaluator, decayed Beta
priors, existing pack contract, and single-process deployment until evidence warrants a change.

Non-goals: framework migration, microservices, blanket multi-agent expansion, score-averaging
committees, transcript RAG for judging, mandatory Postgres/accounts for local practice, CV upload
before JD text, full-duplex voice first, job matching, or visual redesign as a release prerequisite.

Assumptions: one maintainer, one host/process, controlled spending, text-first EN/VN/mixed use.
A trusted pilot shares an explicit trust boundary: the shared token is access control to the
installation, **not private accounts**. Use localhost/private access or a deliberately restricted
pilot with agreed visibility; if Candidates require private histories from each other, use the
public-isolation branch before onboarding them. Candidate IDs are not proof of identity.
No concurrency capacity, cost per Session, or latency SLO has been measured in this pass.

## Revalidated baseline — evidence, not inherited audit verdicts

**Verified** below means inspected code, not a newly executed runtime test. **Historical** means
an existing dated artifact. **Inference** requires the named execution before treating it as proven.
Private `.env`, transcripts, local usage data, and untracked research/audit files are not evidence
of deployed production behavior. Existing untracked documents are left untouched.

| Area | Current evidence | Planning consequence |
| --- | --- | --- |
| Usage storage | **Verified:** [usage.py](../../src/interview_coach/usage.py), `DEFAULT_LEDGER_PATH` / `_append`, defaults to `/app/logs` in this image and drops writes on `OSError`; [Dockerfile](../../Dockerfile) grants write ownership to `/app/state`; [compose](../../docker-compose.yml) sets the other state paths but not `COACH_USAGE_LEDGER`. **Inference:** stock container accounting can fail unless overridden; not container-tested here. | M0 first slice; prove writable persistence and visible failure. API health alone is insufficient. |
| Budget | **Verified:** preflight, quota latch, per-run rails and resume paths already exist in [usage.py](../../src/interview_coach/usage.py) and [web_api.py](../../src/interview_coach/web_api.py). Start check and reservation are separate; `supervisor.question_node` catches quota under generic failure, appends `failed`, and increments `question_count`. | Extend rails, do not rebuild them; reuse #80/#119. Protect concurrent admission and stop at the failing call boundary. |
| Durability | **Verified:** one `run_question` node wraps the whole [Micro-loop](../../src/interview_coach/microloop.py); turns stay local until return. Web answers have only an `answer` field, enter a RAM queue, and have no durable-answer ACK or deduplication key. | M1 needs an explicit durable turn/ACK contract. Existing question-level resume does not prove accepted-answer survival. |
| Existing hardening | **Verified:** shared-token/Origin checks, same-Session duplicate-socket rejection, single-worker guard, disk exports, typed Candidate cancellation, atomic rename + process lock for Skill ledger exist. [0019](0019-session-resume-edge-cases.md) records CLI clock/unknown-ID/history fixes. | Keep completed work. A lock protecting a file does not prove idempotent evidence application or account ownership. |
| Resource limits | **Verified:** `max_questions <= 10`; no answer length cap, no upper bound on requested elapsed time, no global Session cap; input/output queues unbounded; `QueueCandidate.answer` waits until answer/cancel. | M0 adds missing bounds and lifecycle cleanup; do not claim existing question cap bounds wall time or memory. |
| Telemetry | **Verified:** per-call latency/provider/model/tokens/outcome logging and usage `session_scope` exist; [telemetry.py](../../src/interview_coach/telemetry.py) uses a process-global Counter; trace lines lack Session/turn/role. | M2 completes attribution and tests overlap; not “no observability”. |
| Judge quality | **Verified:** [role clients](../../src/interview_coach/llm.py) pin judge, and `bench_passed` checks score/delivery bands, not paired fairness. [Rubric](../../src/interview_coach/rubric.py) still lacks middle anchors in depth/system_thinking. **Historical:** [2026-07-27](../audits/calibration-bench-2026-07-27.md) reports 35/35 at k=3, temperature 0.2, but paired max absolute delta 2.00. | Keep `openai/gpt-5.4-mini`; separate fairness gate. Do not carry forward the resolved #92 flake as an open defect or infer fairness from 35/35. |
| Progress/report | **Verified:** [ledger.py](../../src/interview_coach/ledger.py) overwrites one latest snapshot per Candidate, not a timeline. Planner copies LLM `readiness_estimate`; web displays a percentage. Web start payload has no pack selection. | M2 explains readiness limits; M3 adds durable Session snapshots and web pack selection. No forced score improvement or calibrated hiring-probability claim. |
| Operations | **Verified:** checkpoint cleanup is startup-only; completed state retained in RAM; no unified export/ledger delete policy. **Historical:** [deploy §8](../deploy.md#8-verified-not-asserted) tested unanswered-question restart and completed exports, not every turn cut point or restore. | M1 expands crash coverage; M3 establishes small local retention/restore; M4 covers account-wide deletion/backup handling. |
| Eval coverage | **Verified:** unit/replay helpers exist; [CI](../../.github/workflows/ci.yml) runs pytest and frontend checks, not a live calibration campaign or browser E2E. [Replay artifact](../../src/interview_coach/replay.py) lacks explicit pack/model/prompt provenance. | Reuse tests and runner; M2 adds minimal release evidence and pack-aware replay provenance. Historical test counts are not a new green suite. |

## Old plan → keep / reorder / add / defer

| Existing plan/reference | Decision | Reason / destination |
| --- | --- | --- |
| Completed critical path 0001 → 0010; UI/eval [0012](0012-ui-and-eval-discipline.md) | Keep | Working architecture and learning sequence; no rewrite. |
| R-25 [#80](https://github.com/nekloyh/get-hired/issues/80), quota [#119](https://github.com/nekloyh/get-hired/issues/119); Docker [#66](https://github.com/nekloyh/get-hired/issues/66) | Reorder + extend to M0 | Existing rails are partial; accounting and scarcity handling precede more consumers. |
| Question resume [0019](0019-session-resume-edge-cases.md), lifecycle [0017](0017-web-cancel-lifecycle-correctness.md) | Keep completed scope; add M1 continuation | Per-turn ACK, crash recovery and idempotency exceed question-level resume. Do not reopen completed acceptance claims indiscriminately. |
| Minimal trace R-26 [#81](https://github.com/nekloyh/get-hired/issues/81) | Keep + extend in M2 | Attribution/isolation are needed before trusting cost and trajectories. No observability dashboard required. |
| Judge [0022](0022-bilingual-judge-calibration-bench.md), anchors [#96](https://github.com/nekloyh/get-hired/issues/96), [#103](https://github.com/nekloyh/get-hired/issues/103), replay [0029](0029-simulated-candidate-replay-bench.md) / [#113](https://github.com/nekloyh/get-hired/issues/113) | Reorder to M2 | Independent fairness and replay gates precede product expansion. Check pending anchor work before duplicating it. |
| Dashboard [0035](0035-progress-dashboard.md) / #83 “Later” | Move to M3; correct storage premise | Core repeat-practice loop is next after reliability/quality, without accounts as a pilot dependency. |
| Pack [0025](0025-question-pack-platform.md) CLI support | Keep; add web adapter in M3 | Expose validated existing packs; no taxonomy rewrite needed. |
| CV/JD [0037](0037-cv-import.md) / #86 upload-first | Split: JD text M3; CV upload deferred | JD describes requirements, not Candidate mastery. Smaller input adapter tests utility before document parsing/storage. |
| Accounts/Postgres [0036](0036-accounts-postgres.md) / #84 | Conditional M4 | Ownership mandatory before public launch; database migration is a separately justified implementation choice, not a pilot blocker. |
| Reskin [0034](0034-frontend-redesign.md) / #60, chrome i18n #85 | Defer broad reskin; allow targeted UX in M3 | Feedback comprehension and repeat practice matter before visual polish; reuse existing work when resumed. |
| E1/E2/E4/E5/E6, ADR 0001/0002 amendments, 0011/0014 | Preserve Proposed; defer experiments until M2 evidence tooling | No automatic policy-only Supervisor, evidence folding, derived-confidence cutover, or dynamic taxonomy. |
| RAG upgrades #68, routing savings, multi-worker/service split | Conditional M6 | Need a measured retrieval, cost or load problem; framework trends are not a trigger. |
| Voice | Add gated M5 spike, then separate implementation decision | No current STT/TTS baseline. Judge must retain an inspectable transcript. |

## Backlog and dependency order

P0 = foundation/safety; P1 = useful, measured core loop; P2 = conditional expansion/experiments.
Public-branch P0 is a **launch blocker**, not a dependency of pilot M3.
Relative effort: S ≈ 1–3, M ≈ 4–7, L ≈ 8–15 focused maintainer days; estimates, not commitments.
Milestone estimates bundle their rows; do not add both estimates. Eval waiting and pilot feedback
can extend calendar time. Entries without an exact issue use the existing slice as parent;
reconcile/create a narrowly scoped subtask only at implementation time, never a duplicate here.

| Work ID | Priority / effort | Work and existing tracker | Depends on / milestone |
| --- | --- | --- | --- |
| F1 | P0 / S | Writable durable usage ledger, visible accounting failure; #66 + #80 | None / M0a |
| F2 | P0 / M | Input/frame/output-token bounds, active Session admission, bounded queues, idle/call deadlines and cleanup; [0017](0017-web-cancel-lifecycle-correctness.md) continuation | F1 / M0b |
| F3 | P0 / M | Atomic budget admission/reservation, quota suspension without failed question; #80 + #119 | F1; integrates F2 / M0b |
| F4 | P0 / L | Durable turn IDs/ACKs/results and idempotent Skill/ledger publication; [0019](0019-session-resume-edge-cases.md) continuation | M0 / M1 |
| Q1 | P1 / M | Session/turn/role/attempt trace, latency and cost baseline; #81 continuation | M1 stable IDs / M2 |
| Q2 | P1 / M | Fairness, grounding, report evidence/readiness limits; #96/#103 + [0022](0022-bilingual-judge-calibration-bench.md), [0011](0011-study-planner-and-export.md) | M1; Q1 for live evidence / M2 |
| Q3 | P1 / M | Small release gate, versioned pack-aware replay; #113 + [0029](0029-simulated-candidate-replay-bench.md) | M1; Q1 / M2 |
| U1 | P1 / M | Session history snapshots, progress, retry entry point; [0035](0035-progress-dashboard.md) / #83 | M2 / M3 |
| U2 | P1 / S | Web selection of allowlisted existing packs; [0025](0025-question-pack-platform.md) continuation | M2 incl. pack-aware replay / M3 |
| U3 | P1 / M | JD text draft → confirmation → existing Diagnostic; [0037](0037-cv-import.md) / #86 | M2; reuse F2 limits / M3 |
| U4 | P1 / S | Local retention/delete policy and offline backup/restore drill; [deploy](../deploy.md) continuation | M1 durable records; before M3 gate |
| A1 | P0 public / L | Accounts and all-path ownership; [0036](0036-accounts-postgres.md) / #84 | M2; current M3 data contract before launch / M4 |
| A2 | P0 public / M | Account deletion/retention, backup/restore, migration decision; #84 + deploy | A1; U4 / M4 |
| V1 | P2 / S | VN/EN/code-switch voice measurement spike | M3 / M5a |
| V2 | P2 / L | Push-to-talk adapter and transcript confirmation | M5a GO; M4 if public / M5b |
| X1 | P2 / S spike, implementation TBD | Load/cost/retrieval experiments, then smallest proven change; #68/#73/#84 as applicable | M2 baseline + M3 demand / M6 |
| X2 | P2 / M per bounded experiment | Proposed ADR experiments, CV upload, reskin; existing referenced issues | M2 gates; separate evidence/ADR decision, not required by M3 |

Dependency path: **M0a → M0b → M1 → M2 → M3** for personal/trusted use.
Public branch: **M2 → M4 preparation**, then **M3 + M4 PASS → public launch**.
M4 may be prepared alongside M3, but must authorize the final M3 routes/data before launch.
Optional: **M3 → M5a → explicit GO → M5b**; public voice also requires M4.
M6 is optional after measured demand, not a prerequisite of launch or practice.

Calendar planning only: days 1–30 aim at M0/M1 and M2 preparation; 31–60 aim at M2/M3;
61–90 consolidate pilot feedback and choose M4 or M5a based on actual demand. This is not a promise
to finish every branch in 90 days. A failed gate shifts the date; a date never waives a gate.

## Evidence contract for every milestone

Each milestone below specifies its outcome, scope, start condition, baseline, tests, thresholds,
artifacts, go/no-go, effort and residual risk. The following common rules apply to **all** of them:

- Record commit SHA + dirty-diff hash if applicable, fixture/eval-set hash, pack version/hash,
  role → provider/model mapping, prompt hash, decoding parameters, environment and commands.
  Mark model fields N/A for offline-only runs; do not label fakes as live quality evidence.
- Put a short result report in `docs/audits/` and link test/eval artifacts. Keep transcripts,
  tokens/secrets and identifying text out of committed logs; use synthetic fixtures or redacted,
  explicitly consented examples. Record sample count, errors/missing results, and test duration.
- **Invariant** thresholds (zero acknowledged-answer loss, zero duplicate evidence, zero cross-state
  contamination) are required semantics, not measured capacity claims. **Existing** thresholds cite
  an ADR/artifact. **Proposed** thresholds are provisional acceptance targets, not proven user SLOs;
  freeze them with the baseline before comparing a candidate implementation, not after seeing red.
- Use the smallest relevant offline regression set per change. Fake-provider integration and E2E
  prove mechanics only. Docker/browser setup may need network downloads; live provider calls always
  need an explicit run budget and recorded configuration. No automatic paid live CI campaign.
- The maintainer records GO/NO-GO plus artifact links. Missing evidence is not PASS. On failure,
  keep the previous working path, fix the failing slice, rerun the affected checks; don't expand
  scope or weaken labels to manufacture green. Recheck upstream gates only when impacted.

## M0 — account for usage and bound work

1. **Outcome:** a text Session cannot silently spend outside the application rails; load and idle
   clients have predictable refusal/suspension behavior.
2. **In scope:** M0a F1 first; then M0b F2/F3. Validate ledger path on the container volume, startup
   and mid-run write health, bounded payloads/queues/admission/deadlines; typed quota propagation
   across Diagnostic, Evaluator, Follow-up and Planner boundaries. Preserve completed evidence
   when suspending. **Out:** turn persistence, new auth, Postgres, new models, load optimization.
3. **Start/dependencies:** current checkout; no prior milestone. Reuse existing usage rails and
   deployment configuration seam. M0a is independently reviewable before M0b.
4. **Acceptance:** running as image UID, synthetic metered call is accounted exactly once and its
   ledger survives restart **and container replacement with the volume retained**. Unwritable or
   corrupt accounting refuses new metered work visibly; failure after a paid call records an
   unresolved accounting condition and prevents further calls until reconciled, never treating
   unknown usage as zero. Two starts racing for one reservation admit at most one. Quota inside a
   question suspends with unchanged `question_count`, no new `failed` item and no Skill update.
   Resume does not recharge a start reservation. Oversized/early/repeated frames, full queues and
   idle sockets cannot grow retained work without bound; cancellation remains deliverable.
5. **Checks:** offline unit fault injection in usage/provider classification; integration of graph
   and both Session drivers with fake quota; barrier-controlled two-start race; disposable Docker
   volume with fake metered provider; one browser suspension/retry E2E. No paid API required.
6. **Baseline:** rails/tests already exist (`test_usage.py`, budget cases in `test_web_api.py`);
   defaults are soft sizing estimates, not a verified provider entitlement. Measure container
   write/restart behavior and admitted/thread/queue counts first; not executed in this plan update.
7. **Pass/fail:** invariants above must all pass. Propose initial numeric input/queue/timeout caps
   from longest supported fixture + a documented margin; record them before boundary tests.
   Test below/at/above each cap. Unknown provider usage is conservative reservation, not free usage.
   In-flight billed calls may complete after a quota stop: record this bounded liability; do not
   promise a hard provider invoice cap without enforced per-call token limits/reservations.
8. **Artifact:** M0a container storage report, M0b fault/race results and a table of chosen limits,
   with redacted refusal/suspend events and before/after ledger totals.
9. **Decision:** GO to M1 only after both subgates; accounting failure or fake failed question is
   NO-GO. Keep metered access restricted while fixing; demo remains available.
10. **Effort/risk:** L overall. Unknown provider usage after transport failure and lifecycle races
    remain concerns; M1 supplies durability during suspension, so M0 alone is not a usable resume guarantee.

## M1 — one durable answer, one durable effect

1. **Outcome:** Candidate can reconnect after an acknowledged answer without retyping or receiving
   duplicate scoring/evidence from an ordinary retry.
2. **In:** F4: explicit Session/question/turn/submission identity; persist input before durable ACK;
   persist evaluation and Follow-up state; deduplicate answer/result/Skill/ledger/export effects;
   coordinate old thread shutdown and reconnect. Keep last-turn evidence semantics. **Out:** fold
   all turn scores, dynamic taxonomy, wholesale graph rewrite, distributed coordination.
3. **Start/dependencies:** M0 PASS. Write a small state-transition contract at the existing
   checkpointer seam before code. Include legacy question-level checkpoints: migrate, or fail with
   a visible unsupported-resume message while preserving old exports; never silently restart them.
4. **Acceptance:** run the cut-point matrix below. ACK means committed storage, not queued or
   locally displayed. Retry same submission returns the same committed result; stale/conflicting
   submissions are rejected. Exactly one evidence application per resolved question and one
   cross-session publication per completion. Two different Sessions interleaved keep distinct
   answers, state and pending Follow-ups, including reconnect while an old call finishes.
   Define same-Candidate concurrent completion semantics explicitly: serialize/reject conflicting
   publication or merge by versioned evidence; never silently overwrite a newer Skill snapshot.
5. **Checks:** one parametrized fake-provider integration matrix + two browser E2Es (ACK/restart
   and Follow-up/reconnect), existing micro-loop/Skill/replay regressions. Use a disposable real
   checkpointer and process termination, not only mocked saver methods. No paid calls required.
6. **Baseline:** question-level `SqliteSaver` persistence and unanswered-question restart from
   deploy §8; no durable ACK protocol today. Capture failing cut-point results before implementing.
7. **Pass/fail:** **invariants:** zero lost ACKed inputs; zero duplicate committed judgments or
   Skill evidence; zero state mixing; pending unACKed submission can safely be retried. A crash
   after provider response but before local commit may require a second external call if the API
   cannot deduplicate it: report/cap its cost, accept only one committed judgment and evidence
   update. Do not promise exactly-once external inference across this uncertainty window.
8. **Artifact:** transition diagram/table, each cut-point result, before/after input/result/evidence
   IDs and hashes, browser test report; sanitized examples only.
9. **Decision:** NO-GO on any invariant breach; retain restricted pilot and fix the boundary.
   GO to M2 only with deterministic recovery and documented external-call uncertainty.
10. **Effort/risk:** L; greatest risk is coordinating DB commit, graph checkpoint and external
    response. Prefer a small durable record at the current seam; justify any schema change.

| Cut point (test both disconnect and process restart) | Expected recovery |
| --- | --- |
| Before server receives answer | Pending question remains; no evidence; client may resend. |
| Received/queued but before input commit | No durable ACK; retry stores one input. |
| Input committed, before ACK delivered | Resend discovers same input; no second turn. |
| ACK delivered, before/during grading | Stored answer resumes grading; no request to retype. |
| Grading result committed, before Skill/checkpoint publication | Reuse result; apply evidence once at question resolution. |
| Waiting for Follow-up after an earlier evaluated turn | Restore exact pending Follow-up and prior turns. |
| After Skill publication or completion, before client observes result | Retry/reconnect replays outcome, not effects; ledger timestamp/history are not duplicated. |

## M2 — explain and measure the judge and the loop

1. **Outcome:** an incorrect answer/score can be traced to the responsible turn, role and evidence;
   bilingual quality is a separate release decision from score-band pass rate.
2. **In:** Q1–Q3; complete correlated trace, representative latency/cost measurement, fairness gate,
   grounded report and readiness wording, production-config calibration and replay provenance.
   **Out:** replace current judge without evidence, deploy Proposed confidence/evidence/Supervisor
   changes, tracing SaaS dashboard, repeated whole live benches for unrelated UI edits.
3. **Start/dependencies:** M1 PASS supplies stable turn IDs; M0 accounting funds bounded live eval.
   Reuse 0022/0029 and pending anchor work. Freeze labels/prompt/model/pack before comparisons.
4. **Acceptance:** two concurrent fake Sessions attribute every attempted call exactly once to
   Session/turn/role/attempt, including retries and errors; aggregate tokens agree with known fake
   usage, unknown usage is labeled. Report shows rubric dimensions, answer-linked evidence, missing
   evidence and a concrete next exercise. Readiness is explicitly a coaching estimate from limited
   observations, not a probability of hiring; unprobed Skills and model/prompt version are visible.
   Calibration uses production role configuration; fairness reports every paired total and
   per-dimension delta. Replay records pack/rotation/provenance and checks trajectory/rails.
5. **Checks:** offline trace overlap/grounding/renderer tests + existing replay fixtures and one
   targeted changed-path replay; manual report review. Later, budgeted `coach bench --k 3` at the
   production sampler and a small EN/VN/mixed text Session sample. Do not run these live here.
6. **Baseline:** historical July 27: 35/35 k=3 at temperature 0.2, paired mean |Δ| 0.17/max 2.00;
   not a September measurement. Existing replay live evidence is [0029's July 7 run](0029-simulated-candidate-replay-bench.md)
   on a different judge. First measure current full-Session tokens/cost and p50/p95 from answer
   submission to feedback, excluding human think time; log per-role timing, sample size, cold/warm
   retrieval and model config. Small-sample p95 is descriptive, not an SLA.
7. **Pass/fail:** **existing:** ADR 0009 median-of-k=3 at production temperature, no score/delivery
   range regressions, investigate straddles and |bias| > 0.5 at n ≥ 8. **Proposed separate fairness
   gate:** paired max holistic |Δ| ≤ 1.0; each technical-dimension delta > 1.0 requires adjudication
   and is NO-GO while unexplained. Review the worst pair plus one strong and one weak EN/VN pair
   for equivalent meaning and grounding; no fabricated quote may support a score in this reviewed
   set. These are provisional bounded-sample targets, not proof of population fairness. A second
   reviewer is desirable for disputed labels; unresolved labels block certification of that case.
   **Replay invariants:** ordering/rails maintained on existing fixtures; no extra failed questions
   or duplicated evidence. Supervisor/evidence changes invoke ADR experiment criteria as well.
   **Proposed UX check:** three reviewed reports correctly identify score evidence and limitations;
   any unsupported hiring-probability claim fails. No invented latency/capacity threshold: freeze
   an operating target only after the baseline and user-wait review, then compare changes to it.
8. **Artifact:** calibration report + standalone fairness verdict, trace reconciliation, versioned
   replay and report-review notes, latency/cost table with pricing date/source when costs are priced.
   Record survivor counts/errors under the existing ADR rule; insufficient evidence is not green.
9. **Decision:** GO to M3 when mechanics, fairness and explanation gates pass. If fairness fails,
   keep current judge, diagnose anchors/labels, fix and re-evaluate; do not widen bands. If live
   budget is unavailable, finish offline work but leave live quality gate pending. Existing private
   practice may continue with disclosed limits; do not claim the next phase is certified.
10. **Effort/risk:** L plus live-eval/reviewer scheduling. Small labeled set, stochastic drift and
    self-confidence saturation remain; bench green is not validated readiness or employment prediction.

## M3 — finish the repeat-practice loop (personal/trusted pilot)

1. **Outcome:** Candidate completes an interview, understands one actionable gap, practices it,
   starts another Session and sees an honest comparison of evidence over time.
2. **In:** U1–U4: durable per-Session summary snapshots/history index, dashboard and retry action,
   existing pack selector, bounded JD text draft/confirmation, simple local delete/retention and
   consistent backup/restore. **Out:** accounts/Postgres prerequisite, CV/PDF parsing, new Skill
   taxonomy, job matching, broad reskin, guaranteed positive score deltas.
3. **Start/dependencies:** M2 PASS. Existing disk exports/Skill priors retained; add history at
   completion without treating latest-only ledger as a time series. Prefer current SQLite/storage
   seam. Pack-specific replay must cover the selected built-in/FPT packs. Pilot trust assumptions
   above apply; private per-person history requires M4.
4. **Acceptance:** two fixture Sessions for one Candidate appear after restart with accurate
   positive/zero/negative deltas; repeated completion creates no duplicate history. Show pack,
   difficulty, amount of evidence and judge version so different Sessions aren't falsely equivalent.
   Select an allowlisted pack on web, preserve it on resume; reject unknown IDs, never accept arbitrary
   filesystem paths. JD yields role/company/requirements draft for Candidate confirmation, never
   inferred personal mastery; manual claims remain separate and weak-prior tests pass. Historical
   transcript/coaching text cannot enter Evaluator/Interviewer/Supervisor or Diagnostic scoring
   inputs. A Candidate can find feedback, name one change to practice, and run again.
   Document retention per data class; delete a synthetic Candidate's local data and perform one
   consistent backup/restore in a fresh location, including history/ledger/checkpoints/exports.
5. **Checks:** fixture units for history/deltas/JD validation/prompt boundary, one demo E2E that
   spans two Sessions and pack resume, offline restore/delete drill, then manual pilot review of
   real utility. JD extraction quality and live Sessions use a separately capped API budget.
6. **Baseline:** current report/export and latest priors exist, no dashboard or JD/web-pack flow.
   No measured completion or repeat-use rate. Establish first small cohort counts: Session starts,
   valid completions, distinct Candidates, second Session within 14 days, and one usefulness answer;
   exclude demos/tests and distinguish cancellation/quota/error. No PII in analytics artifacts.
7. **Pass/fail:** mechanical invariants all pass, including zero duplicated history and zero coaching
   memory leakage. **Proposed formative gate:** 3 consenting pilot Candidates (or maintainer for
   personal-only use, explicitly weaker evidence); at least 2/3 complete a Session, explain one
   specific feedback action and voluntarily practice a second time within 14 days. Personal-only
   gate: complete that loop twice and document usability issues, without claiming market validation.
   Record actual counts and denominator; no statistical retention claim. Correctly display unchanged
   or worse scores; perceived improvement is reviewed, not guaranteed. Restore must recover every
   fixture record in the snapshot; measure elapsed time and recovered cutoff, no invented RTO/RPO.
8. **Artifact:** history/E2E report, backup manifest and restored-count comparison, deletion checklist
   per store, anonymous pilot funnel counts and feedback summary with known comparison limits.
9. **Decision:** GO to ongoing pilot when the chosen personal/pilot gate passes. If Candidates do
   not understand or repeat practice, fix feedback/retry UX before voice or wider acquisition.
   This GO does **not** authorize public launch or establish account privacy.
10. **Effort/risk:** L plus 14-day observation window. Small sample, latest-ledger migration and
    score comparability remain risks; initial dashboard is descriptive, not a learning-effect claim.

## M4 — public launch branch: identity and operations

1. **Outcome:** each account accesses only its own interview data, and the operator can delete,
   retain and recover data under a documented policy.
2. **In:** A1/A2; accounts, server-derived ownership, all-path authorization, legacy data mapping,
   retention/delete including backups, restore rehearsal. Evaluate existing Supabase/Postgres
   proposal in 0036 against deployment needs. **Out:** mandatory multi-worker, public anonymous
   paid interviews, voice, broad platform rearchitecture.
3. **Start/dependencies:** preparation after M2; launch requires M3 PASS and tests against final M3
   routes. Inspect #84 before choosing tooling. Accounts/ownership are required regardless of DB;
   Postgres migration requires a recorded reason (hosting/auth integration or measured storage need).
4. **Acceptance:** enumerate every HTTP/WS path for start/answer/cancel/read/list/export/progress/
   resume/delete and every Candidate/Session ID source. Account A cannot read or mutate B, including
   guessed IDs, swapped Candidate IDs, stale/revoked credentials, reconnect and old shared-token
   access. Legacy unowned records must be explicitly assigned by verified migration or quarantined.
   Retention covers checkpoints, answers/results, exports/history, Skill data, traces and backup
   expiry; restored backups cannot silently resurrect deletions. Restore into a clean environment
   recovers ownership and resume consistently. Public mode fails closed when auth is misconfigured.
5. **Checks:** two-account authorization matrix via integration + one browser cross-account test,
   migration on synthetic copied fixtures, expiry/deletion and fresh-environment restore drills;
   rerun M1 crash subset on a changed checkpointer. Use local/disposable auth/DB where feasible;
   hosted integration requires network/service configuration, not a paid LLM campaign.
6. **Baseline:** shared bearer token only; no account ownership; existing export persistence is
   historical evidence, not backup restoration. Use M3 restore baseline; record actual backup
   interval, recovery time and retained-data inventory before deciding operational targets.
7. **Pass/fail:** zero unauthorized read/write/resume across the matrix; zero lost snapshot records,
   duplicate evidence, or resurrected deleted fixtures. Retention deadlines and backup expiry must
   be explicit and tested. **Proposed operational targets:** select RPO/RTO and pilot admission cap
   from measured drills/load, record before launch; no default “50 users” capacity claim. Run a
   small fake-provider load test at the intended cap and one step above: bounded queues/resources,
   correct rejection, no mixed state. Live latency evidence comes from M2, not fake timings.
8. **Artifact:** route/ownership matrix, migration decision and report, retention policy, deletion
   and restore evidence, measured load envelope and rollback/runbook; versions per common contract.
9. **Decision:** public GO only with M3 + M4 PASS and no unresolved P0; otherwise remain restricted
   pilot. Reverting to shared-token mode is not a public fallback. If DB migration fails, preserve
   source data, roll back safely, and keep public launch pending.
10. **Effort/risk:** L plus possible M database migration, re-estimate after decision. Authentication
    integration, legacy ownership and backup erasure are residual risks. Postgres alone does not
    remove process-local Session coordination; keep the single-worker guard until M6 proves otherwise.

## M5 — voice, with a mandatory spike stop point

1. **Outcome:** first determine whether voice preserves technical meaning and scores; only then
   offer push-to-talk with an inspectable, Candidate-confirmed transcript for the existing judge.
2. **In:** M5a V1 compares a small STT/TTS pipeline on VN/EN/code-switch recordings; M5b V2 adds
   voice input/output adapters, transcript edit/confirmation and text fallback. **Out:** full-duplex,
   interruptible realtime agent, direct audio-only judge, nonconsensual audio collection/storage.
3. **Start/dependencies:** M3 PASS and demonstrated interest in voice. M5b cannot start without an
   M5a evidence-based GO; public rollout also requires M4 and audio retention coverage.
4. **Acceptance:** spike measures term errors (negation, acronyms, numbers, ML terminology), ordinary
   transcription errors, score delta versus manually corrected text, and full-chain latency
   (end-of-speech → transcript ready → feedback → first synthesized audio). Implementation preserves
   M1 submission IDs/ACK semantics; judge receives confirmed transcript and duplicate audio retries
   do not create duplicate evidence. Text fallback remains usable on STT/TTS failure.
5. **Checks:** **proposed smallest spike:** 12 consented/synthetic clips, 4 per language mode,
   containing weak/strong and terminology-heavy answers. Human reference transcript and term-error
   review; same pinned judge/config k=3 comparison of raw STT versus reference for score impact.
   Local component tests can be offline; STT/TTS/LLM services and model downloads are explicitly
   budgeted/networked. After GO: one push-to-talk E2E plus M1 retry/crash subset and manual timing.
6. **Baseline:** no current voice implementation or measurement. M5a produces the first baseline
   with device/network/model configuration; M2 text latency is the control, not voice evidence.
7. **Pass/fail:** **proposed:** zero meaning-changing technical-term errors remaining after Candidate
   confirmation in the reviewed set; raw-STT max median score delta ≤ 0.5 on the 1–5 scale versus
   reference. Report raw errors even when confirmation fixes them. Determine acceptable full-chain
   wait in the spike's user review and freeze a numeric target before M5b; do not invent one here.
   A failed score-impact target or unacceptable wait is NO-GO for implementation until another
   bounded spike shows improvement. Small clip set is feasibility evidence, not broad ASR accuracy.
8. **Artifact:** clip manifest without private audio, reference/model versions, error taxonomy and
   score-delta table, stage/end-to-end timings, cost, user-wait review and explicit M5a decision;
   M5b adds E2E/durability evidence and audio retention policy.
9. **Decision:** M5a failure parks voice and preserves text practice; do not build around unmeasured
   transcription. M5b ships only when its E2E, M1 invariants and frozen timing target pass; disable
   voice on regressions without blocking text.
10. **Effort/risk:** M5a S plus bounded API/reviewer time; M5b L, separately authorized in future
    implementation scope. Code-switch/accent coverage and mobile network variance remain uncertain.

## M6 — optimize or scale only a measured bottleneck

1. **Outcome:** a demonstrated resource/cost bottleneck improves without harming Session correctness
   or judging quality; otherwise the simple deployment stays.
2. **In:** X1, one change per experiment: immutable pack/retrieval caching, role routing, accounting
   read-path optimization, or background queue for genuinely asynchronous work. DB/worker/service
   changes only if the measured seam requires them. **Out:** speculative distributed platform.
3. **Start/dependencies:** M2 baseline, M3 demand, defined bottleneck and frozen comparison workload;
   M4 before exposing scaled public use. A background task must have retry/idempotency requirements.
4. **Acceptance:** compare control/candidate with the same pack/model/prompt/workload; record
   CPU/RAM/queue depth, timeouts, p50/p95 and token/cost attribution. Multiple workers additionally
   prove same-Session exclusion, reconnect routing and all M1 invariants across processes.
5. **Checks:** small stepped fake-provider load around measured intended admission cap; targeted
   integration/crash tests; cache-key/invalidation tests. Role/model changes require applicable
   calibration/grounding tests; Supervisor changes require replay, both when both are touched.
6. **Baseline:** no measured capacity today; single-worker guard is present. Reuse M2/M4 numbers,
   refreshing only stale or changed workload measurements. Historical RAG shelf results do not
   prove a bottleneck for the current pack/deployment.
7. **Pass/fail:** **proposed:** predeclare a useful gain in the chosen metric after baseline and
   before the experiment; no regression against M1/M2 gates or the chosen operating envelope.
   Without a measurable gain or demand, NO-GO for added complexity. No invented N-Sessions promise.
8. **Artifact:** before/after load/cost report, exact config, relevant eval results, failure/recovery
   results and decision documenting ongoing operational cost.
9. **Decision:** adopt only the smallest winning change; otherwise retain current architecture.
   Worker/DB coordination changes need a narrowly scoped ADR with this evidence before rollout.
10. **Effort/risk:** S measurement spike; implementation re-estimated from evidence, not pre-approved.
    Synthetic load approximates providers poorly; limited live timing and rollback remain necessary.

## ADR decisions that this plan does not silently accept

- ADR 0001 E1 (LLM deviation vs policy-only) and ADR 0002 E2 (evidence semantics) remain Proposed.
  M1 durability preserves last-turn-wins. Any future change needs the named replay comparison and
  recorded accept/reject decision; an old negative/positive data point is not a fresh experiment.
- ADR 0011 E4/E5 derived confidence and ADR 0014 E6 taxonomy remain Proposed. Neither blocks M3
  with existing packs. Their old sample counts/thresholds must be reviewed against current labels
  before executing an experiment; this plan neither changes their status nor waives their gates.
- M2's standalone fairness threshold is a **proposed addition** to ADR 0009, not an already accepted
  ADR rule. Evidence needed: bilingual label adjudication, k=3 distributions at production config,
  false-positive review and a separate fairness verdict; then propose an explicit addendum.
- M1's durable ACK/effect contract may need a persistence ADR if the storage/graph boundary changes;
  bring the cut-point results and minimal design. It does not authorize changing scoring semantics.
- M4 separates identity from the bundled Postgres proposal in slice 0036. Record the storage/auth
  choice using deployment requirements and migration/restore evidence; do not represent a Proposed
  framework choice or an unmeasured capacity argument as an Accepted ADR.

## Start here — the first reviewable vertical slice

**M0a / F1: one fake metered call → persisted usage → container replacement → same budget balance.**
Reuse #66/#80, check their current threads, and attach a subtask there if needed. Limit the first
implementation to usage-path wiring, accounting-health failure behavior and its disposable-container
verification. Demonstrate (1) successful write as UID 10001, (2) retained balance after replacement,
(3) a deliberately unwritable path visibly blocks metered continuation rather than dropping spend.
No live model needed. Produce the M0a report and review that slice before admission/quota work;
M0a green alone does not certify the rest of M0 or permit public launch.
