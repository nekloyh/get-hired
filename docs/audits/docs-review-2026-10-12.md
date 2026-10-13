# Docs and ADR review — 2026-10-12

- **Commit reviewed:** `2ceaf81` (tag `v0.3.0`, `main`). ADR 0015 was read at `c1baafd` on
  `docs/adr-0015-store` (PR #161), with its gate record and spike.
- **Scope:** every evergreen document (`CLAUDE.md`, `CONTEXT.md`, `README.md`, the `CHANGELOG.md`
  entries down to 0.3.0, `docs/*.md`, `docs/issues/README.md`, the index text of `docs/audits/README.md`,
  `.env.example`), the 37 slice specs, the 12 ADRs on `main` and ADR 0015. Records in `docs/audits/`
  and `docs/research/` were used as evidence, not audited.
- **Method:** 24 auditors, one per document cluster, slice-spec batch, ADR group or cross-cutting
  check (status leaks, contradictions, terminology, issue references and orphans, the maintainer's
  kickoff facts). Each auditor extracted every checkable claim and gave it `TRUE`, `FALSE` or
  `UNVERIFIABLE` with evidence. Every finding then went to a second agent told to refute it. Drift a
  verifier said the auditor missed, and `TRUE` verdicts a verifier overturned, went to a third agent.
  86 agents in all, read-only, **0 provider tokens**.
- **Gate at `2ceaf81`:** `scripts/gate.sh` OK: ruff, ruff format, mypy, pytest 1020 passed / 8
  deselected / 2 xfailed, npm lint, npm test 38 passed, npm build.
- **The findings themselves** are in [`docs-review-2026-10-12.findings.jsonl`](docs-review-2026-10-12.findings.jsonl),
  one verified finding per line: id, document, kind, severity, verdict, the exact quote, evidence and
  the proposed fix. Evidence cites lines at `2ceaf81`, which a dated record may do.

## Limits of this record

- The per-claim tables the auditors wrote were lost when the machine rebooted mid-run. The claim
  **counts** survive; the individual `TRUE` verdicts do not.
- Spot check of the `TRUE` column: each auditor named the 5 `TRUE` verdicts it was least sure of,
  and the verifier overturned **12 of 122**. That is an upper bound on the error of the least certain
  `TRUE` verdicts, not the rate for the whole column.
- 65 suspected misses were dropped by a cap before the third pass and are **not verified**. They are
  not in the findings file.
- The verifiers refuted 35 findings and corrected 237 (verdict, severity, quote, evidence or fix).
  Only the corrected version is recorded.

## 1. Claims by verdict

| Document group | TRUE | FALSE | UNVERIFIABLE |
|---|---:|---:|---:|
| `CLAUDE.md`, `CONTEXT.md`, `README.md`, `CHANGELOG.md` | 378 | 55 | 1 |
| `docs/*.md`, the two README indexes, `.env.example` | 568 | 96 | 7 |
| ADRs (12 on `main` + 0015) | 353 | 80 | 38 |
| Slice specs (37) | 654 | 192 | 17 |
| Cross-cutting checks | 273 | 60 | 0 |
| **Total (2,772 claims)** | **2,222** | **487** | **63** |

## 2. Findings that survived verification: 664

| Severity | Count | | Kind | Count |
|---|---:|---|---|---:|
| high | 46 | | false claim | 279 |
| medium | 294 | | status leaked into an evergreen doc | 134 |
| low | 324 | | contradiction between documents | 56 |
| | | | unverifiable claim | 44 |
| | | | other | 35 |
| | | | terminology off `CONTEXT.md` | 31 |
| | | | issue reference drift | 21 |
| | | | line-citation rot | 17 |
| | | | tracker drift | 14 |
| | | | broken link | 13 |
| | | | slice spec vs closed issue | 10 |
| | | | orphan document | 5 |
| | | | kickoff fact correction | 5 |

By document: slice specs 202 (9 high), ADRs 155 (10 high), `README.md` 64 (8 high),
`docs/data-model.md` 41, `docs/pilot-runbook.md` 32 (6 high), `CLAUDE.md` 32 (5 high),
`docs/roadmap.md` 28, `.env.example` 20 (4 high), `CHANGELOG.md` 20, `docs/audits/README.md` 19,
`docs/deploy.md` 18, `CONTEXT.md` 16, `docs/issues/README.md` 14, two docstrings in `src/` (out of
scope for a docs change) and one research record.

## 3. The 46 high findings, by root cause

| # | Root cause | Finding ids |
|---|---|---|
| 1 | **#96 was closed by accident.** Release PR #165's body says "the anchor fixes #96/#103" and GitHub read "fixes #96" as a closing keyword. `rubric.DIMENSION_GUIDE` still has no band 3 for `depth` or `system_thinking`, and nine documents name #96 as the owner of open work. `mlops_awareness` has anchors at 1 and 5 only, 8 of the 35 bench cases weight it, and no issue tracks it | U1-01, U3-01, U4-01, X1-04, X2-02, X2-18, X4-01, A4-03, A5-01 |
| 2 | **`README.md` states a gate result.** "the bench is green (29/29)" and "`coach bench` 20/20". `judge.lock` names a RED 34/35 artifact on 35 cases. The red case, `vnlp_segmentation_weak_vi`, moved with no code change | U2-01, X1-01, X2-01, X4-05, M-14, M-8 |
| 3 | **`README.md` setup fails.** `PRIMARY_PROVIDER=groq` or `zenmux` makes `config.Settings._require_bench_validated_judge` raise, so every LLM command fails; "any other configured provider is used as fallback" is also wrong | M-11 |
| 4 | **Slice specs on the critical path describe removed or reversed behaviour.** 0006 keeps "the higher-confidence of the two passes"; `evaluator.evaluate` escalates to the Panel and keeps its verdict unconditionally, and a test pins that. 0001 and 0005 run `coach evaluate` and `coach interview`, both deleted in `4f8cdf3`. 0019 says a resumed Session is not ended by the time rail; that holds only for the CLI | S1-01, S1-16, S1-24, X2-05, X3-01, X4-06, M-48, M-54, S3-01 |
| 5 | **`CLAUDE.md`: "All LLM calls go through the `LLMRouter`".** The judge, and every role with a `ROLE_*` override, get a pinned client from `llm._pinned_role_client` that bypasses the router by design | U1-02, M-5 |
| 6 | **`.env.example` budget arithmetic is stale, and part of it is never read from `.env`.** The per-Session ceiling is `usage.session_token_budget` = 243,000 for 5×4, not 766,800 (changed in `e6c5ef4`); the worst case is 394 calls, not 284. Six variables are read from `os.environ` only, so under `uv run` they are ignored when set in `.env` (Docker passes them through `env_file`) | U6-01, U6-02, U6-03, U6-04 |
| 7 | **`docs/pilot-runbook.md` checks that cannot pass.** The certbot one-liner fails on a fresh checkout (no `.well-known/acme-challenge/`); the `'Answer refused'` and `'still finishing'` greps match no log line (both are socket frames only); pre-flight line 1 covers the Groq key, while #139 and the judge need the OpenAI key rotated too | U7-01, U7-02, U7-03, X2-03, M-44, M-45 |
| 8 | **ADR text that misdescribes the code.** ADR 0010's `Status:` line still says "until it lands" (#73 closed, PR #95 merged 2026-07-19). ADR 0001 says `follow_up_recommended` is judged "over the full exchange"; `evaluator._build_messages` sends one turn. ADR 0002 says the question cap keeps one critical Skill from starving the rest; `supervisor._extra_probe_required` can. ADR 0007 calls the paired EN/VN answers the regression proof; `bench.bench_passed` gates each case's band only. ADR 0009(h) gives a `--only a b` form that argparse rejects | X1-05, A6-01, A1-01, A1-08, A4-01, A5-06 |
| 9 | **ADR 0015's gate record overstates what was measured.** "Both gate conditions hold": the restore check never ran `ledger.load_priors` on the restored copy, and no held (`.unreconciled`) row was an input. "Keep the legacy readers for one release so a rollback can still read them": `v0.3.0`, the rollback point, cannot read the renamed `*.migrated-<date>` files | A8-01, A8-02 |
| 10 | **`docs/data-model.md` names the wrong writer.** `ledger.save_posteriors` has no production caller; the web and CLI completion paths call `ledger.save_measured_posteriors` → `ledger.update_posteriors` | U5-01 |

## 4. Defects in code found on the way

These are not documentation findings. They are recorded here so that they reach the tracker; no
code was changed.

| Defect | Evidence at `2ceaf81` | Verified how |
|---|---|---|
| A web resume does not reset the Session clock, so a Session suspended by Budget exhaustion and resumed on the web after the daily reset can be ended by the time rail | only `cli_session._cmd_session` calls `graph.update_state(config, {"started_at": time.time()})`; `web_session_driver._run_session_thread(resume=True)` streams with no update; `supervisor.decide_next_move` applies `max_elapsed_seconds` | code reading by two agents; no test drives it |
| A quota error on the primary followed by a failing fallback is untested inside a question | `interviewer.generate_follow_up` and `seeds.render_seed_question` catch only `StructuredOutputError` | code reading (ADR 0005 review) |
| `mlops_awareness` has BARS anchors at 1 and 5 only, the same language-fairness hole ADR 0009(d) names, with no issue | `rubric.DIMENSION_GUIDE['mlops_awareness']`; 8/35 cases weight it | measured offline |
| The bench gate has no EN/VN pair tolerance | `bench.bench_passed` reads only per-case `within_band` and `delivery_within_band`; `bench.language_deltas` feeds the report only | code reading + `tests/test_bench.py` |
| `usage.estimated_session_tokens` (5,200 per question) underestimates multi-turn questions about 2x | the 2026-10-12 live smoke: 26,478 tokens for 2 questions, one of them 4 turns | arithmetic on the record |

## 5. ADR review

On 2026-10-13 the maintainer **paused all ADR decisions** pending a product re-orientation. Nothing
below changes an ADR or its `Status:` line. Full section-by-section reviews, with the verifiers'
corrections and draft amendments, are in the workflow result named above and are kept as input for
that review.

| ADR | Code at `2ceaf81` | Recommendation (review input) |
|---|---|---|
| 0001 | hierarchy holds; the Proposed amendment is not implemented and E1 never ran | amend the text; E1 is ~1.0M tokens and 8–12 h |
| 0002 | partial: a self-claim sets the prior mean; the cap does not prevent starvation; E2 ran once (item 2 only, n=1, negative) | amend; E2 needs 2 more personas, ~0.1M tokens |
| 0003 | the core holds; the addenda describe MiMo plumbing removed in `3f19c99` | amend; E3 never ran, ~0.7–1.2M tokens |
| 0004 | historical | keep, with a dated note that the Micro-loop was never migrated |
| 0005 | holds; the text omits `usage.AccountingUnavailable` and the quota-then-failover case | amend, and file the web-resume defect |
| 0006 | holds and is tested (`tests/test_prompt_isolation.py`) | amend the wording: `raw_mastery` also crosses Sessions |
| 0007 | implemented; the gate does not measure EN/VN deltas | amend, or add a pair gate |
| 0008 | lint holds; selection and rotation are misdescribed | amend and point to ADR 0014 |
| 0009 | enforced in code | amend four wrong records, the #96 sentences and the `--only` form |
| 0010 | implemented | amend the `Status:` line and the Why section |
| 0011 | Proposed; E4 and E5 never ran; E4 is written for 29 cases | amend the gates before any run; E5 (~2.7–6M tokens) not now |
| 0014 | Proposed; its premises reproduce | amend the scope; the unknown-role warning can stand alone |
| 0015 | Proposed; the measurements reproduce | accept with amendments: legacy readers in 0.3.x, a complete restore check |

## 6. The kickoff facts

| Fact as given | Verdict | What holds |
|---|---|---|
| The judge is `gpt-5.4-mini`, pinned in code | TRUE | pinned by `config.BENCH_VALIDATED_JUDGES` and `llm.build_role_clients`; no failover; the model id itself comes from `.env.example`, and `COACH_ALLOW_UNVALIDATED_JUDGE` is an audited escape hatch |
| `test_judge_lock` goes red on any change to what the judge is sent | PARTLY | any code change on the three `judge_lock` walks at the default temperature; not replies, not provider-side drift |
| 34/35 is a known red owned by #96 and #103 | PARTLY | 34/35 holds; the red case is `vnlp_segmentation_weak_vi` and its owner is #96, which is closed by accident |
| `coach bench` spends only judge tokens | TRUE | `bench._evaluate_case` → `evaluator.evaluate`; ~181k tokens per k=3 confirm on the locked artifact |
| MiMo is gone; Groq can never be the judge | PARTLY | MiMo is gone from code; Groq can hold the judge role only through the escape hatch, never by failover |
| One live Session is ~26.5k tokens | PARTLY | one 2-question English Session with one 4-turn question; a default 5-question Session is unmeasured |
| E1, E3–E6 never ran; E2 is n=1 and negative | TRUE | still true at `2ceaf81` |
| The priority order (1) learn (2) usable tool (3) signal | TRUE as written | stated consistently; on 2026-10-13 the maintainer re-ordered it for the next stage (see the plan of that date) |
