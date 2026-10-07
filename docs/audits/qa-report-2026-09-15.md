# QA report — branch `audit/stabilize-2026-09-14` @ `60787d4`

Scope: QA of the 7 commits after `main` (`2dac711`), plus the status of every prior-audit finding, plus a
hunt for what the prior audit missed, plus a plan to reach a stable milestone.

Method: every gate re-run locally; every commit's diff read; new tests proved real by reverting their
source to `main` in throwaway git worktrees under `/tmp`; the Docker image built from HEAD and driven
through real WebSocket sessions. `AUDIT.md`, commit messages and code comments were treated as claims,
not evidence. The repo was never modified — `git status` is clean apart from this file.

Commands are reproducible: `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, mypy cache outside the
repo, every test run under `timeout 300`.

---

## 1. Verdict

**GO-WITH-FIXES.** Tag after M-0 (below), not today.

The branch is a strict improvement on `main` on every axis I can measure: all gates green and repeatable
(848 pytest ×3 runs, identical; vitest 27; ruff/mypy/eslint/tsc/build clean), both HIGH bugs it targeted
are genuinely fixed and pinned by characterisation tests that assert the exact M0 acceptance wording, the
judge is provably untouched (`git diff main..HEAD -- evaluator.py rubric.py data/bench/` is empty), and
the image builds from HEAD and runs a complete Session as uid 10001 with state surviving container
replacement.

It is not taggable yet, for one reason above all: **QA-01**. Pressing Start on the session id the UI
itself persists — read-only, never cleared, rotated only by a button most users will never press —
silently overwrites the previous interview's report, with no warning and no recoverable copy. Measured,
not inferred, and confirmed by two adversarial verifiers.

Behind it sit ten more HIGH findings. The sharpest: a second pilot user typing the same Candidate name
inherits and then destroys the first one's Skill history (**QA-02**); one Candidate's provider hiccup
lowers a *different* Candidate's scored confidence through a process-global counter (**QA-03**); the
ADR 0009 judge gate checks the provider but not the model, so one `.env` line silently swaps the judge
(**QA-10**, pre-existing); and the WebSocket API will score an answer against the wrong question if any
client double-sends, because nothing on the server binds an answer to its question (**NEW-01**).

Every one of these is a bounded fix — M-0 is ~37 h and eight of its sixteen tasks can start in parallel.

---

## 2. QA by commit

`git log --oneline main..HEAD`, oldest first. Test counts measured per commit in an isolated worktree.

| sha | Main claim | Verdict | Finding |
|---|---|---|---|
| `3ea1275` | Land the uncommitted M0a usage-ledger work "as-is" (21 files +1,149/−77, 4 untracked paths) | **PASS-WITH-NOTE** | "As-is" is cryptographically proven for the slice half: `git diff 2dac711 3ea1275 -- .env.example Dockerfile docker-compose.yml docs/deploy.md src/interview_coach tests \| sha256sum` reproduces the hash recorded at `docs/audits/m0a-usage-ledger-2026-09-13.md:14`. 805→833 tests confirmed. But this is the first review of the fault-latch machinery and it carries QA-04, QA-12, QA-13. The planning-docs half is unverifiable (no pre-commit hash exists). |
| `a576501` | Docs-only: the forensic audit report | **PASS-WITH-NOTE** | Genuinely docs-only (`git diff --raw` = one `A AUDIT.md`). 48 citations spot-checked: 40 TRUE, 5 OVERSTATED, **3 FALSE** — §3.4's dead-code list names three *live* symbols (`_generate_follow_up_json`, `TranscriptItem.to_dict`, `cli._utc_date`, the last with 3 call sites). Acting on that list unedited would have broken the build. |
| `cf4e40e` | Sync `types.ts` with the wire format; render panel/evidence verdicts; untrack caches; 32→27 real vitest tests | **PASS-WITH-NOTE** | 10/14 claims TRUE. `types.ts:105` still declares `trace: Record<string, unknown>` while `session_serde.py:49-58` sends ten concrete fields, so the sync is incomplete. The Committee block renders 5 of the 10 data points the export prints (`ReportView.tsx:160-173` vs `exporter.py:180-198`). The "32→27" arithmetic is wrong: 25 distinct before, 27 after — tests were *added*, not just de-duplicated. QA-16. |
| `4f8cdf3` | Quota suspends instead of a `failed` question (GH #119); `schema_version`; dedup; eval catches now log | **PASS-WITH-NOTE** | 20/25 claims TRUE and the headline is real and well-tested. Four overstatements, one of which matters: "re-raised past **every** failure-isolation net" is false at three nets (QA-05). "Every other command exits 2 through one dispatcher" is false for `bench`/`forge`/`eval-harness` (QA-14). `schema_version` is stamped only in `initial_session_state`, so a pre-branch Session resumed after this commit keeps writing unversioned checkpoints forever (QA-11). |
| `bd41425` | Docs-only: `docs/data-model.md` + two glossary entries | **PASS-WITH-NOTE** | Docs-only confirmed. 273 citations auto-resolved, **0 out of range** — the most precise document on the branch. "Every store" is overstated: the post-mortem Markdown writer (`postmortem.py:398-399`) and one usage-ledger writer are absent. |
| `9bc067d` | Reconnect race closed; inputs bounded; RAM evicted; atomic cap; lazy `app` | **PASS-WITH-NOTE** | 16/19 claims TRUE. Every bound verified at the wire against the running container (§3 note). The reconnect mechanism (`web_api.py:1001-1035`) is careful and correct. One claim is false: "the export is written before the state enters the cache, so an evicted id **always** has its file" — `_persist_export` swallows `OSError` with only a log (`web_api.py:1081-1091`), reproduced on a read-only exports dir. QA-06, QA-09. |
| `3f19c99` | Remove MiMo and `disable_thinking`; default provider → `openai` | **PASS** | Clean. 853→848 is exactly the 5 MiMo-only tests; no live-path assertion lost. Zero `mimo` references remain in `src/`, `tests/`, `scripts/`, `.github/` or the container files; the 20 surviving doc mentions are historical records the commit says it kept on purpose, and `README.md:37` now correctly says MiMo is retired. `config.py:63` is `extra="ignore"`, so a stale `MIMO_API_KEY` in a live `.env` is inert (verified by loading real `Settings()`). |
| `60787d4` | Docs: execution log + corrections; data-model cites re-pinned | **PASS-WITH-NOTE** | Docs-only confirmed, and the per-commit gate numbers in the execution log are all exactly right (independently re-measured: 833/833/833/840/840/853/848/848). But of the 5 entries in "Corrections to this report", **4 are themselves wrong** about what they are correcting, and two execution-log claims are false: "goldens byte-identical" for `4f8cdf3` (the replay golden gained `schema_version`) and "`ruff format` would reflow 19 pre-existing test files" (measured: **18** files at HEAD, only 13 of them tests). QA-17. |

---

## 3. QA findings

Severity: CRITICAL = data/money loss or compromise likely in **normal** use; HIGH = same under plausible
misuse or concurrency; MEDIUM = bounded correctness defect; LOW = hygiene.

"Measured" means I or a verifier executed the repro and recorded the output.

The eleven most severe findings were each put through **two independent adversarial verifiers** whose
default answer was REFUTED — one attacking reachability and existing guards, one re-deriving every
citation and re-running the measurement. **None was refuted.** Four were downgraded and two upgraded;
those corrections are applied below and marked. `QA-01` is the one place I disagree with the verifiers:
I read "a returning Candidate presses Start instead of Resume" as normal use (CRITICAL); both read it as
user error (HIGH). The fix is the same either way and it is the first task in M-0.

| id | sev | file:line | what | concrete failure | fix (1 line) |
|---|---|---|---|---|---|
| QA-01 | **HIGH\*** | `web_api.py:899` | A fresh `start_session` on an id that already has a checkpoint silently restarts the graph over it and overwrites the persisted report. `web_api.py:899-901` builds `initial_state` whenever `not resume`, with no existence check at all. The CLI has a *partial* guard — `cli.py:447-451` refuses only when the existing Session's status is **not** COMPLETE (an in-flight guard, not an overwrite guard) — and the web has none. | **Measured.** `SetupPanel.tsx:63` renders the session id `readOnly` from `localStorage`, which `sessionId.ts:45-52` never clears; only the "New session" button rotates it. A returning Candidate presses Start → `exports/<id>.md` is overwritten (md5 `c90c671…` → `80f7b28…`), the checkpoint is restarted over it, and yesterday's report is unrecoverable — the endpoint reads RAM, then the file, never the checkpoint (`web_api.py:689-701`). | Refuse a fresh start when `_checkpoint_values` is non-empty — in-flight *and* completed — telling the client to resume or rotate; the CLI needs the completed half too. |
| QA-02 | **HIGH** | `web_api.py:94`, `:913` → `ledger.py:194` | `candidate_id` is free text with no validation, no ownership binding and no secret, and is the **only** key into the cross-session Skill ledger — read on start, destructively replaced on completion. | Two pilot users share one token. B types `minh` into the Candidate-id box on B's own session id: `load_priors` hands B all of A's per-Skill mastery, and on completion `save_posteriors` **replaces** A's record with B's. No error, no log, no audit trail. | Derive the ledger key server-side (HMAC of token identity + name), or refuse a `candidate_id` not already bound to this token; constrain to `[A-Za-z0-9_-]{1,64}`. |
| QA-03 | **HIGH** | `telemetry.py:18` → `evaluator.py:905` | `telemetry._counters` is one process-wide `Counter`, but `web_api.py:314` runs one daemon thread per Session. `evaluate()` derives "did *this* judgment need folds or retries?" by diffing that global around its own judge call. | **Measured.** Two concurrent Sessions: B's judge reply needs one sanitizer fold; A's judgment is spotless. A's `_noise_events` sees B's counter move, `apply_noise_haircut` caps A's confidence 0.95→0.85, and A's Beta evidence weight drops. One Candidate's provider hiccup permanently alters another Candidate's scored evidence — ADR 0005's exact prohibition. | Back the counters with a `ContextVar` (the `_SESSION_ID` ContextVar at `usage.py:264` is the pattern), or return fold counts from `chat_json` alongside the parsed model. |
| QA-04 | **MEDIUM** *(HIGH as reported; both verifiers said MEDIUM)* | `usage.py:436` | `_parked_faults` is the only reader of the `.unreconciled` sidecar and turns every `OSError` into "no faults" (`text = ""`), with **no log** — unlike `_all_rows`, which logs (`usage.py:642-647`). A truncated last line is skipped by a bare `except json.JSONDecodeError: continue`. | The state volume was once written by a root container, so `/app/state/usage-ledger.jsonl.unreconciled` is root-owned 0600 while the ledger stays writable — the exact permission class M0a was built for. A parked billed call vanishes; `accounting_gate()` returns `None`; metered work resumes as if the spend never happened. Fails **open** on the money path. | On `OSError`/`UnicodeDecodeError` return a synthetic unresolved fault naming the unreadable path, and log it. |
| QA-05 | **HIGH** | `supervisor.py:399`, `:332`; `postmortem.py:201` | `4f8cdf3` claims the typed stops are "re-raised past every failure-isolation net". Three nets were missed. `supervisor.py:399` re-raises `ProviderQuotaExhausted` but **not** `AccountingUnavailable`; `supervisor.py:332` (study-plan node) and `postmortem.py:201` re-raise neither. | **Measured** (3 independent agents + me). Ledger goes unwritable mid-Session → the Supervisor's decide call raises `AccountingUnavailable` → swallowed → deterministic fallback → the Session walks one question deeper making more metered calls, and the exported decision trail mislabels the cause as "a provider transport error". This is the M0 rule "prevents further calls until reconciled". | `supervisor.py:395`: `except (AccountingUnavailable, ProviderQuotaExhausted): raise` (already imported at `:52`); same for the two other nets. |
| QA-06 | **MEDIUM** *(downgraded: the escalation precondition is measured dormant on the production judge)* | `evaluator.py:928` | The panel is **advisory** — it refines an already-valid judgment — but its three calls are unguarded. Any provider error in the Skeptic or Advocate propagates and destroys the valid first-pass judgment. | **Measured.** Candidate answers Q3/3; the judge's first pass is valid but escalates; the Skeptic hits `APIConnectionError` surviving all 4 transport attempts. `evaluate` raises, `question_node` records `stop_reason: "failed"` with zero evidence for a question the Candidate answered correctly. Infrastructure noise → Skill evidence. | Wrap `evaluator.py:928-936` and fall back to `_finalize(first, …, panel_suppressed=True)` — the field already exists at `evaluator.py:159`. |
| QA-07 | **MEDIUM** *(downgraded by both verifiers)* | `skill.py:168` | `evidence_weight_for` short-circuits on `evaluation.panel is not None` and returns `panel_agreement_weight(disagreement)`, never consulting `confidence` — so the two deterministic guards that exist precisely to distrust a degraded judgment are bypassed on the escalated path. | A judgment whose citations were all blanked by sanitize-and-keep (`evaluator.py:814-835`, `evidence_degraded=True`, confidence capped 0.95→0.40) escalates, the two panel voices happen to agree (disagreement 0.0), and the judgment enters the Beta at **maximum** weight. The worse the evidence, the more the panel fires, the heavier it counts. | `min(panel_agreement_weight(disagreement), confidence_weight(evaluation.confidence))`. |
| QA-08 | **HIGH** | `web_api.py:839` | The daily question-cap reservation is taken with the client-supplied `max_questions` **before** the payload is semantically validated (`:908-912`) and is never released when the run asks nothing. | **Measured.** 48 × `{"type":"start_session","max_questions":10,"claimed_skills":{"not_a_real_skill":3}}` — each dies at `:908` before any provider call, each has already appended a `questions: 10` row. `questions_today` reaches 480/480 and every pilot user is locked out for the UTC day at zero provider cost. A cancelling or crashing client does the same accidentally. | Validate `CandidateProfile` before `reserve_questions`, and release the unused remainder when the run ends. |
| QA-09 | **HIGH** | `ledger.py:184`, `usage.py:900` | Both ledgers are guarded only by `threading.Lock`, which is process-local — but the CLI is a second process writing the same files. `ledger.py:46-56` justifies this by "the server is documented single-process"; `coach session`/`coach postmortem` falsify that. | **Measured.** Two processes both pass `reserve_questions(identity, questions=10)` against a cap of 10 → `questions_today = 20`. (I widened the check→append window by 1.5 s to make it deterministic; unmodified, only timing luck separates them.) On the Skill ledger the same window means a `coach postmortem --candidate alice` concurrent with a web completion silently erases one of the two records — `save_posteriors` never raises. | `fcntl.flock` on each target for the whole read-modify-write, in addition to the in-process lock. |
| QA-10 | **HIGH** *(contested: one verifier says MEDIUM; pre-existing — byte-identical on `main`)* | `config.py:34`, `:218` | `_require_bench_validated_judge` gates only the **provider** against `BENCH_VALIDATED_JUDGE_PROVIDERS = frozenset({"openai"})`. Neither the **model** nor the **base_url** is validated; `openai_model` (`:75`) and `role_judge_model` (`:128`) are free-form `str`. `COACH_ALLOW_UNVALIDATED_JUDGE` (`config.py:92`) disables even the provider check — an escape hatch ADR 0009 does not grant. | **Measured** — resolved judge per config permutation, real `.env` never read: nothing set → refused (`primary provider 'openai' is not configured`); `PRIMARY_PROVIDER=groq` → **correctly refused** with the ADR 0009 message, so the *provider* pin works; but `OPENAI_MODEL=totally-not-benched-9000` → `judge provider='openai' model='totally-not-benched-9000'`, and `OPENAI_MODEL=gpt-4o-mini` → accepted, both silently. So an operator who hits a rate limit, edits one line and runs `docker compose up -d` gets a clean start: no error, no warning, `/api/health` unchanged. Every Evaluation from that moment is scored by a model with no bench artifact and flows into the Beta states and the Skill ledger. ADR 0009 says a judge change is bench-gated; the gate is provider-shaped, not model-shaped. | Allowlist bench-validated `(provider, model)` pairs, validate `base_url`, and log the resolved judge provider+model+base_url at startup. |
| QA-11 | **MEDIUM** | `supervisor.py:163` | `SESSION_SCHEMA_VERSION` is written in exactly one place — `initial_session_state`. No node ever returns it. | **Measured.** A `main`-shaped checkpoint (built by running `main`'s own code against a real `SqliteSaver`) resumes on HEAD, runs to `complete`, is exported and has its posteriors saved — and the final state **still** carries no `schema_version`. Separately, `schema_version` is **write-only**: zero read sites in `src/`, `tests/`, `scripts/` or `web/`; a checkpoint stamped `schema_version: 99` resumes on HEAD without a word. Same for `LEDGER_SCHEMA_VERSION`. There is no validate, no refuse, no migrate. | Stamp it on every node return (or in a graph-level reducer), and add one reader that fails visibly on an unknown version. |
| QA-12 | **MEDIUM** | `usage.py:371-376` | `_flush_faults` takes `_FAULT_LOCK` only to snapshot `pending`, releases it, then writes and marks `parked` outside the lock. | **Measured.** Two Sessions flush concurrently → the same billed 1,500-token fault is appended to the sidecar twice → `coach usage --reconcile` replays it twice → 1,500 tokens become 3,000 in the money ledger, permanently. | Hold `_FAULT_LOCK` across write-and-mark, or mark `parked` optimistically and roll back on `OSError`. |
| QA-13 | **MEDIUM** | `usage.py:593` | `reconcile_accounting` replays every held row into the ledger and only then rewrites the sidecar; the rewrite is a whole-file `write_text`. | **Measured** (1,740 → 3,480 tokens). If the sidecar rewrite fails, the CLI tells the operator the rows are still held and to retry — and the retry replays them all again. Separately, `write_text` from the CLI process erases any fault the server appended in the meantime. | Stamp each fault with a uuid, dedupe on replay, and remove rows individually as they land. |
| QA-14 | **MEDIUM** | `bench.py:190`, `eval_harness.py:119`, `forge.py:389` | The per-case nets catch the two typed operator stops, so they never reach `cli._dispatch:1233-1246`. | A quota death mid-bench becomes a bench **report** full of error rows written into `docs/audits/`, instead of an honest "we ran out of quota". Under ADR 0009 that report is the judge gate's artifact — an infrastructure failure can be read as a judge regression. | Re-raise `ProviderQuotaExhausted`/`AccountingUnavailable` out of the per-case nets. |
| QA-15 | **MEDIUM** | `web_api.py:107` + `App.tsx:313` | The 20k answer cap exists only on the server. The client clears the draft and appends the chat bubble **before** the server can reject. | Candidate pastes a 21,000-char design write-up and hits Send: the draft box empties, the answer appears as theirs, then a banner shows a raw pydantic `ValidationError`, the reducer flips to terminal `error`, and the composer is disabled. The answer is destroyed and the Session is wedged. | `maxLength={20000}` + a counter on the textarea, and a non-terminal error kind that keeps `currentQuestion`. |
| QA-16 | **MEDIUM** | `types.ts:105`, `ReportView.tsx:160-173` | `cf4e40e`'s sync is incomplete: the per-turn `trace` is still `Record<string, unknown>` against ten concrete server fields, and the Committee block drops `initial_confidence` and both voices' `argument`/`key_evidence`. | The UI still cannot show the evidence the export shows, which is the defect `cf4e40e` set out to close. | Declare `TraceRecord` in `types.ts`; render the five missing Committee fields. |
| QA-17 | **LOW** | `AUDIT.md:462`, `:474`, `:483` | The execution log and the "Corrections" section overstate. "Goldens byte-identical" for `4f8cdf3` is false; "19 pre-existing test files" is false (18, 13 of them tests); 4 of 5 corrections misattribute the section they correct. | A reader trusting the log believes the wire format was frozen byte-identically across the quota fix. | Re-pin those three lines; scope "goldens" to the two the commit message actually names. |

**Wire-level probes against the running container — all PASSED** (evidence for the `9bc067d` row above):
bad `Origin` → 403 before accept; **missing `Origin` → accepted** (non-browser clients bypass the Origin
rule — §3.1 row 1 of the old audit, still true); no auth frame → close 1008; non-object frame →
`session_error`, session not wedged; `max_elapsed_seconds` > 14400 → refused; `max_questions` > 10 →
refused; answer > 20000 chars → refused; 30 queued answers → `"Answer dropped: earlier answers are still
being processed."`; two simultaneous reconnects → one resumes, the other gets `"This Session id already
has an active connection."`; a disconnect-then-resume session produced exactly 3 transcript items for
`max_questions=3` with no duplicates; quota death on the Diagnostic → `"Session suspended: openai daily
quota exhausted … Nothing was checkpointed yet; start a new Session after the reset."`

### 3.1 Project invariants (ADRs / `CLAUDE.md` / `CONTEXT.md`)

| Invariant | Verdict | Evidence |
|---|---|---|
| **ADR 0001** — the Supervisor makes exactly one "deviate?" LLM judgment; the Evaluator is the only judge; the Interviewer never scores | **COMPLIANT** | All 15 LLM call sites in `src/` correspond 1:1 between `main` and HEAD, same modules and counts (supervisor 1, evaluator 3, diagnostic 1, interviewer, forge 2, …). The Interviewer still consumes `Evaluation` without producing one. |
| **ADR 0003** — tool-calling confined to the Interviewer; every grant carries an eval gate | **COMPLIANT** | Exactly one tool (`LOOKUP_CONCEPT_TOOL`) and one grant site (`interviewer.py:413-422`, `tool_choice` forced), byte-identical to `main:414-423`. `chat_with_tools` has one real caller plus the router passthrough (`llm.py:812`). |
| **ADR 0009 / 0010** — the judge is pinned and any judge change is bench-gated | **VIOLATED in part** | The *provider* pin is enforced and correct (`PRIMARY_PROVIDER=groq` is refused with the ADR 0009 message). The *model* is not gated at all — see **QA-10**. The prompt, anchors and bench cases are untouched, and the literal `chat.completions.create(**kwargs)` of a real judge call is **byte-identical** between `main` and HEAD (whole-kwargs SHA-256 `7a7d60db3f29…`), so nothing on this branch moved the judge's provider, model, decoding parameters, retry policy or failover reachability. `bench.py`'s diff is 4 lines — an import, a logger, a blank line and one `logger.warning` — and cannot move a verdict. |
| **ADR 0005** — infrastructure noise must never corrupt Skill evidence; intent must never become evidence; budget exhaustion is its own third category | **VIOLATED in part** | The category the branch set out to fix is genuinely fixed and pinned by `tests/test_supervisor.py:340-370`. But four other paths still turn infrastructure into evidence: **QA-03** (cross-session telemetry bleed), **QA-06** (a panel-voice outage → zero-evidence `failed`), **QA-07** (degraded evidence at maximum weight), **NEW-16** (`failed` items rendered to the Supervisor as `score=0.00`). **QA-05** leaves one budget-exhaustion path degrading instead of suspending. |
| **ADR 0002** — correlations prior-only; Role criticality flexes prior *strength* and the termination bar, never the prior *mean* | **COMPLIANT** (with a defect) | `_CORRELATIONS`, `CRITICALITY_SETTINGS`, `_ROLE_CRITICALITY`, `_seed_prior` and `_initial_mastery_means` are byte-identical to `main`; measured across all three criticality tiers at five requested means, the prior **mean** is invariant and only the strength moves. `apply_evaluation` is still difficulty-blind. The `ledger.py` "fold" is proven behaviour-preserving by a 186-case differential test against `main`'s two loaders (0 mismatches under exact `repr()` float equality). The strength formula can still go non-positive (**NEW-18**). |
| **ADR 0006** — probing and judging surfaces never see prior transcripts | **COMPLIANT** | `git diff main..HEAD -- src/` contains no new `"role":`, `SYSTEM_PROMPT` or `_build_*_messages` line; `_build_supervisor_messages` and `_evidence_summary` are byte-identical to `main`; `evaluator.py`, `rubric.py` and `session_serde.py` are not in the diff at all. Scoring memory remains decayed Beta priors. But see **NEW-30**: the enforcement test ADR 0006 says exists does not. |
| **Proposed ADRs must not be in code** — ADR 0001's 2026-07-19 amendment (E1/E4), ADR 0002's addendum items 1–3 (E2), ADR 0011 (E4/E5), ADR 0014 (E6) | **COMPLIANT** | Filtered by *section header*, not filename. None is implemented: no difficulty weighting, no derived confidence, no multi-vote, no per-turn evidence folding, no pack-data taxonomy. `microloop.py:204` still says "keeps the last, not the best". |
| **`LLMRouter` is the only path to a provider** — no agent imports a provider client | **COMPLIANT** | `build_client`/`build_role_clients` (`llm.py:847`, `:966`) are the only constructors; the judge bypasses the *router* by design (ADR 0009 addendum a), not the module. |

---

---

## 4. Status of the prior audit at HEAD

170 rows judged. **48 DONE · 34 PARTIAL · 80 NOT DONE · 8 WRONG IN AUDIT.**

### 4.1 Phase 6 — "week one" (the audit's own to-do list)

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Land or revert the uncommitted M0a work | **DONE** | `3ea1275`; slice-half diff hash matches `docs/audits/m0a-usage-ledger-2026-09-13.md:14` |
| 2 | Write the data model down; `schema_version` on the checkpoint **and both ledgers** | **PARTIAL** | `docs/data-model.md` exists and is precise; `supervisor.py:163` + `ledger.py:193` stamp two of them; the **usage** JSONL stays unversioned (argued at `docs/data-model.md:129`), and QA-11 limits the checkpoint stamp |
| 3 | Characterisation test: reconnect race | **DONE** | `tests/test_web_api.py:1807`, `:1876`, `:1914` |
| 4 | Characterisation test: #119 | **DONE** | `tests/test_supervisor.py:340-370` asserts `question_count == 1`, no `failed` item, **and** `skill_states[second_skill] == prior` — the exact M0 wording |
| 5 | Delete the dead list; untrack the web caches | **PARTIAL** | Caches untracked and ignored; MiMo, `disable_thinking`, demos, `build_embedding_similarity`, `_skill_state` gone. Still present: `SelfCritiqueTrace`, `docs/reference/*`, the two unloaded `data/` outputs |
| 6 | Freeze the wire format with a golden covering panel + evidence-degraded + failed | **PARTIAL** | The golden genuinely covers `schema_version` — proven by mutation: dropping the key from `initial_session_state` and regenerating makes `replay-trajectory.json` differ while the other five stay identical. But no golden covers a **panel** or a **`failed`** item, and the `types.ts` sync is incomplete (QA-16) |
| 7 | Move `create_app()` out of import time; delete the conftest workaround | **PARTIAL** | `app` is lazy (`web_api.py:749-758`) and tested (`tests/test_web_api.py`); the conftest env-popping workaround still exists |
| 8 | Bound inputs and evict RAM | **DONE** | All four bounds verified at the wire (§3); `MAX_COMPLETED_SESSIONS_IN_MEMORY = 64` at `web_api.py:85` |
| 9 | Set the token; remove dead-provider keys from `.env`; confirm `auth_required` | **NOT DONE** | `.env` key names (values not read): `PRIMARY_PROVIDER, MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL, GROQ_API_KEY, GROQ_MODEL, OPENAI_API_KEY, OPENAI_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT_SECONDS`. **No `COACH_AUTH_TOKEN`** — verified by loading real `Settings()`: `auth token set: False`. The 3 MiMo keys are inert (`config.py:63` `extra="ignore"`) but are live credentials for a retired service |
| 10 | Purge the fabricated ledger rows **and add a provenance field** | **PARTIAL** | Rows purged; the process-level guard landed (`tests/conftest.py:48-66`). The durable half did **not**: `record_usage` (`usage.py:281-305`) writes `ts/provider/model/prompt_tokens/completion_tokens/session` — no `source`. A test that sets its own `COACH_USAGE_LEDGER` (which the fixture explicitly permits) can still write rows indistinguishable from spend |

### 4.2 Damage report — what moved

| Section | DONE | PARTIAL | NOT DONE | Notable |
|---|---|---|---|---|
| §3.1 Security (7) | 1 | 2 | 4 | Both HIGH rows (open API when unset; no per-record ownership) unchanged. Every "INFO (good)" item re-verified with no regression. |
| §3.2 Correctness (16) | 11 | 1 | 4 | **Both HIGH rows closed and tested.** Still open: ledger read amplification, CLI bounds, the 100 ms busy-poll. |
| §3.3 Duplication (20) | 3 | 1 | 16 | Only the three the commit named were collapsed. Three *new* duplicates landed (a TS hand-mirror of the Evaluator's pydantic models; two inline copies of the token sum in `usage.py`). |
| §3.4 Dead code (18 + 9 stale comments) | 12 | 4 | 8 | Four stale comments fixed. `resources.py:3` ("the production path is Chroma") survives and is still wrong for every default path. |
| §3.5 Inconsistency (10) | 0 | 2 | 8 | Untouched by design. |
| §3.6 God objects (6) | 0 | 3 | 3 | `cli.py` 1,414→**1,246**, `web_api.py` 992→**1,122** (grew), `usage.py` 1,033→**1,054**, `llm.py` 985→**927**, `supervisor.py` 767→**772**, `evaluator.py` 966 (unchanged). Neither split happened. |
| §3.7 Coupling (8) | 0 | 0 | 8 | Untouched by design. |
| §3.8 Tests (12) | 6 | 6 | 3 | Suite re-confirmed real. The web double-registration is fixed. The three named flake candidates all survive. |
| Phase 4 buckets (20) | 8 | 9 | 3 | No KEEP module degraded. |

### 4.3 The audit was wrong about these (8)

| Claim | Truth at HEAD |
|---|---|
| `_generate_follow_up_json` is fake-only, ≈60 deletable lines | Live: `DemoLLMClient` inherits `supports_tool_calls = False`, so `interviewer.py:604` is demo mode's only follow-up path |
| `TranscriptItem.to_dict` + `_raw` guard have no caller | `tests/test_session_serde.py:35,40` exist precisely to exercise the guard |
| `cli._utc_date` is dead | Three call sites: `cli.py:809`, `:813`, and one more |
| `fixtures.FixtureQuestion` referenced only inside its file | Used by `eval_harness.py` |
| `resources.py`'s Chroma half is unreachable from every runtime caller | Reachable via `--resource-store chroma` (`cli.py:996`, `:1073`); it is *unused by default*, not unreachable. The stale comment at `resources.py:3` is the real defect |
| `ruff format` would reflow 19 pre-existing **test** files | 18 files at HEAD, of which 13 are tests; 28 at `main`. "19" occurs at no commit |
| `4f8cdf3` left goldens byte-identical | `tests/golden/replay-trajectory.json` gained `"schema_version": 1` |
| 4 of the 5 "Corrections to this report" | Misattribute the section they correct (e.g. `question_count == 2` appears nowhere in `AUDIT.md`) |

### 4.4 Explicitly-tracked open items

| Item | Status | Evidence |
|---|---|---|
| `.env` token + surplus MiMo keys | **NOT DONE** | §4.1 item 9 |
| `pytest-timeout` | **NOT DONE** | absent from `pyproject.toml` `[dependency-groups]`; no `timeout-minutes` in `.github/workflows/ci.yml`. Four of the new tests **hang** rather than fail if their guard regresses |
| `web_api.py` split | **NOT DONE** | 1,122 lines — grew by 130 |
| `cli.py` split | **NOT DONE** | 1,246 lines (was 1,414) |
| Usage ledger re-parsed per call; never rotated | **NOT DONE** | **Measured**: `budget_stop_reason` makes **3–4 full parses of the entire all-time JSONL per call**, and it is called once per graph stream event — ~30–40 full parses per 3-question Session. At 5,000 rows that is 15,000–20,000 row-scans per call |
| `postmortem.py` handler for the two typed exceptions | **PARTIAL** | `cli._dispatch:1233-1246` catches both centrally for every subcommand, so the module needs no handler of its own — but `postmortem.py:201` is a net that re-raises only `CandidateIntent`, so a quota death in the study-plan end-matter degrades silently and exits 0 (QA-05) |
| `_generate_follow_up_json`, `TranscriptItem.to_dict` | **WRONG IN AUDIT** | both live — see §4.3 |
| `SelfCritiqueTrace`, `docs/reference/*`, MiMo doc mentions | **NOT DONE** (deliberate) | 20 doc files mention MiMo; all are historical records |
| `resources.py` Chroma path | **WRONG IN AUDIT** | see §4.3 |
| Auth/ownership: one shared token, client-chosen session id | **NOT DONE** | `web_api.py:679-688`; and now QA-02 makes `candidate_id` a second unowned key |
| Skill ledger keeps only the last snapshot (blocks #83) | **NOT DONE** | `ledger.py:194-197` |
| `STALE_RUNTIME_JOIN_SECONDS` (120 s) < a 4-attempt retry storm | **CONFIRMED, still open** | measured in the container: a single unreachable provider gives 4 × 60 s attempts plus 2 s/5 s/… backoff ≈ **4.2 minutes**, during which a reconnect is told to retry |

---

## 5. New findings the prior audit missed

| id | sev | file:line | what | concrete failure | fix (1 line) |
|---|---|---|---|---|---|
| NEW-01 | **HIGH** | `web_api.py:267-277`, `microloop.py:247` | **No server-side binding between an answer and the question it answers.** The queue is FIFO with no turn id; integrity depends entirely on client UI state. | **Measured.** Send A1 and A2 while only Q1 is pending: Q1 (`ml_fundamentals`) is scored with A1, Q2 (`deep_learning`) is scored with **A2 — text typed for Q1** — and Q3 (`mlops`) gets the answer meant for Q2. Every question after the first is misattributed, the Session completes normally with no error, and the shifted scores are written to the Skill ledger. The shipped React client blocks the trigger (`sessionReducer.ts:89-96` clears `currentQuestion`), but the WS API accepts it from any client. This is M1/F4 — but the consequence is evidence corruption, not just a durability gap. | Carry a `question_id`/`turn_id` on `candidate_answer` and reject a mismatch. |
| NEW-02 | **HIGH** | `web_api.py:966` + `supervisor.py:199` | **`resume_session` on an id with no checkpoint leaks a raw LangGraph internal error.** The CLI guards this explicitly (`cli.py:406-410`: *"An unknown --resume id would otherwise surface langgraph's EmptyInputError as a bare traceback"*); the web does not. | **Measured** against the container: any unknown/swept id returns `session_started {resumed: true}` then `session_error: "EmptyInputError: Received no input for __start__"`. Reachable in normal use: `localStorage` keeps the id forever while checkpoints have a 7-day TTL, so a Candidate returning after 8 days clicks the UI's own "Reconnect & Resume" and is hard-stuck on a poisoned id. | Port `cli.py:406-410`: when `_checkpoint_values` is empty, emit the friendly unknown-id message instead of streaming. |
| NEW-03 | **MEDIUM** | `web_api.py:1018` | The 120 s stale-thread join runs on the **asyncio default executor** (`run_in_executor(None, …)`), sized `min(32, cpu+4)` = 24 here. "One waiter per id" bounds it per id, not globally. | A mass reconnect — nginx restart, network blip, a cohort resuming after sleep — with slow provider calls in flight pins up to 24 executor threads for up to 120 s each; the 25th reconnect queues inside the executor, so its socket stalls before it can even send a refusal. Not empirically triggered; arithmetic and citation only. | Use a dedicated bounded `ThreadPoolExecutor` for joins, and cap total concurrent waiters. |
| NEW-04 | **MEDIUM** | `exporter.py:18` + `web_api.py:1081-1091` | The Markdown export is written non-atomically (`write_text`) and `_persist_export` swallows `OSError` with only a log. | Volume fills as a Session completes: the file is truncated to 0, partially written, and the exception is logged and dropped. `session_completed` is emitted normally, the Candidate sees a finished interview, the id is later evicted from RAM, and the endpoint serves the truncated file with **200 OK**. | Temp file + `fsync` + `os.replace` (reuse `ledger.py:216`), and fall back to rendering from the checkpoint. |
| NEW-05 | **MEDIUM** | `usage.py:331` | `clear_quota_exhausted` is global. Any one Candidate's resume un-latches the dead-quota flag for **everyone**. | Provider returns `insufficient_quota`; A resumes, writing `quota_retry`. B, C and D now pass `start_refusal_reason` (`usage.py:846-853`), start Sessions and each die on the first call. One user's retry converts a clean refusal into three broken interviews. | Scope the retry grant to the resuming session id. |
| NEW-06 | **MEDIUM** | `usage.py:823` | The daily token rail counts one provider only, so every failover call is billed, recorded, and budgeted against nothing. | With a configured fallback, a primary returning empty completions bills the primary once and the fallback once per call; only the primary's spend is counted toward `LLM_DAILY_TOKEN_BUDGET`. | Sum every provider's spend in `remaining_today`, and add a failover multiplier to `worst_case_question_calls`. |
| NEW-07 | **MEDIUM** | `llm.py:492` | A billed call whose response carries no parseable `usage` object is recorded as **zero tokens**, or not at all, and latches no fault. | **Measured** against the real `OpenAIClient._record_usage`: the no-`usage` case writes no ledger row; a gateway using `input_tokens`/`output_tokens` writes `prompt_tokens: 0, completion_tokens: 0`. Spend becomes invisible to every rail — the failure mode M0a exists to prevent. | Treat an unparseable token count as an accounting fault (`_latch_fault(billed=True)`), not as a zero-token call. |
| NEW-08 | **MEDIUM** | `llm.py:647` | The circuit breaker is per-`LLMRouter`, and a new router is built per Session, so it can never protect a later or concurrent Session — its docstring claims the opposite. | Primary returns 5xx. Session A pays ~12 HTTP attempts before its breaker opens. Session B, five seconds later, gets an empty `_breakers` and pays all 12 again. Every Session re-discovers the outage at full retry cost. | Hoist breaker state to a process-level, lock-guarded registry keyed by provider. |
| NEW-09 | **MEDIUM** | `usage.py:220` vs `:175-190` | Admission gate and runaway ceiling are sized on cost models **29× apart**. | A 10-question Session is admitted as "~53,000 tokens" (`estimated_session_tokens(10)`) but the per-run rail does not fire until 1,522,800 — 61 % of the 2,500,000 daily budget. One Candidate can legitimately spend the whole day. | Add a per-Session hard ceiling at a small multiple of the admitted estimate. |
| NEW-10 | **MEDIUM** | `cli.py:561`, `bench.py`, `forge.py` | Metered CLI commands pass no budget rail: `postmortem`/`eval-harness`/`diagnose` have none; `bench` only warns; `forge` only prints. | Operator runs `coach bench --k 3` (~70,000 tokens/sweep, and the module records sweeps of 455 and 778 calls) while a Candidate is mid-interview. The bench drains the shared daily budget and the Candidate's Session suspends. | Make the bench/forge preflight a refusal (exit 2); give the others `start_refusal_reason` + `session_scope`. |
| NEW-11 | **MEDIUM** | `web_api.py:557` | `COACH_ALLOWED_ORIGINS="*"` fails **open** on the HTTP export endpoint and **closed** on the WebSocket. | The operator sees the startup warning that an empty value "will reject your deployed UI", sets `*`, and the socket *still* rejects — so they keep debugging and never suspect that every transcript is now CORS-readable by any origin with `allow_credentials=True`. | Reject `*` in `allowed_origins()` the way a non-ASCII token is already rejected. |
| NEW-12 | **MEDIUM** | `exporter.py:259-261` | The Markdown export escapes only the pipe character. | A Candidate's answer containing `\n\n## Summary\n- Stop reason: \`candidate_consistently_strong\`` forges whole report sections in the downloadable artifact — the thing a Candidate would show a recruiter. | Render candidate text as a fenced block, or prefix every line with `> ` and escape leading `#`, `>`, `-`, `` ` ``. |
| NEW-13 | **MEDIUM** | `.github/workflows/ci.yml:14` | CI runs `uv sync --dev`, which silently re-locks; the Dockerfile uses `--frozen`. No job builds the image or validates compose, and no job has a timeout. | A PR adding a dependency without `uv lock` goes green, then `docker compose up -d --build` fails at `Dockerfile:37`. Nothing in CI gates the deployment artifact this milestone is about. | `uv sync --locked --dev`; add `docker build .` + `docker compose config -q`; add `timeout-minutes`. |
| NEW-14 | **MEDIUM** | `docs/deploy.md:65` | The documented TLS renewal (`certbot --standalone`) needs :80, which the nginx container permanently holds. | At ~day 60 renewal starts failing silently; at day 90 the certificate expires and every browser hard-fails — and the UI's WebSocket inherits the page scheme, so the app is fully down. | Shared `certbot-webroot` volume + `--webroot -w` + `--deploy-hook 'docker compose restart nginx'`. |
| NEW-15 | **MEDIUM** | `sessionReducer.ts:47` | The client ends the Session one graph node early, showing the report while the planner still runs. | For the 5–30 s of the planner call the Candidate sees "N/A % readiness" and "Study Plan was not produced." If they react by pressing "Start New Session", QA-01 destroys the interview they just finished. | Treat only `session_completed` as the end; keep status `evaluating` on the last `state_update`. |
| NEW-16 | **MEDIUM** | `supervisor.py:714` | Infrastructure `failed` questions are rendered into the Supervisor prompt as `RESOLVED QUESTION EVIDENCE … score=0.00`. | A provider timeout on Q1 becomes, to the Supervisor's LLM, evidence that the Candidate scored 0 on a MUST_HAVE Skill — steering the rest of the interview. Infrastructure noise reaching a decision surface. | Render failed items as `NOT ASKED (infrastructure failure; no evidence)`. |
| NEW-17 | **MEDIUM** | `ledger.py:194` | Skills that were never probed are persisted as **posteriors** from the Candidate's own self-claim. | Claim `vietnamese_nlp = 5/5`, never get asked about it: the ledger stores mastery 0.800 with zero evidence. Next Session the stale self-claim outranks the Candidate's honest `1/5` and is reported as measured progress. | Persist only Skills with a transcript item carrying `evidence_weight > 0`. |
| NEW-18 | **HIGH** *(upgraded by both verifiers)* | `diagnostic.py:378` | `prior_strength = mean*(1-mean)/target_variance - 1.0` goes non-positive whenever `mean*(1-mean) <= target_variance`. | A strong returning Candidate on a MUST_HAVE Skill seeds a degenerate Beta, so one further answer swings mastery far more than the evidence warrants. | Clamp the mean to the criticality's representable interval, or floor `prior_strength` at a small positive epsilon. |
| NEW-19 | **HIGH** *(upgraded; one verifier says MEDIUM)* | `cli.py:493` | After a quota death the CLI offers `--resume` whenever *any* checkpoint exists under the id — including an already-**completed** earlier interview. | Candidate finishes a Session on the default id, later starts another that dies on the Diagnostic, follows the printed `coach session --resume …`, and gets exit 0 and a full "(complete)" report **for the earlier interview**, presented as this run's result. | Offer `--resume` only when the checkpoint's status is not COMPLETE. |
| NEW-20 | **MEDIUM** | `cli.py:404` | CLI `--resume` has no in-flight guard, so a shell resume can drive the same checkpoint thread as a live web Session from a second process. | The web prints the resume command on a budget stop; the operator runs it; `cli.py:413` stamps a fresh `started_at` into the shared checkpoint while the web thread is still streaming. Two writers, one `thread_id`. | Apply the in-flight check to `--resume`, or take an OS lock on `<checkpoint-db>.<session-id>`. |
| NEW-28 | **LOW** | `ledger.py:193` | The new `_meta` key shares a namespace with user-supplied candidate ids. | A Candidate (or a harness) runs `coach session --candidate _meta`. Their posteriors persist and warm-start correctly — then the *next* Candidate to complete a Session overwrites `data["_meta"]` with `{"schema_version": 1}` and destroys that record silently. Introduced by `4f8cdf3`. | Nest records under their own key (`{"_meta": …, "candidates": {…}}`) with a flat-layout fallback in the loader, or reject `_meta` as a candidate id. |
| NEW-29 | **LOW** | `ledger.py:101-106` | Both ledger loaders document a "never raises" contract and violate it on a non-UTF-8 file (pre-existing). | The ledger acquires invalid UTF-8 from outside the writer — volume corruption, a restore by another tool, a hand edit. The next Session start calls `load_priors`, `UnicodeDecodeError` escapes the guard, and the Session aborts on a file that is supposed to degrade to "no priors". | Add `UnicodeDecodeError` to the read guard. |
| NEW-30 | **LOW** | `docs/adr/0006-cross-session-memory-as-decayed-priors.md:47` | ADR 0006 names a prompt-construction test as its enforcement mechanism. That test does not exist. | Slice 0035 / GH #83 (coaching memory) is the ADR's own named consumer. If it adds a "last time you struggled with backpressure" string to a shared state helper that `_build_supervisor_messages` or the Evaluator's builder also reads, nothing fails. | One test module that, for each probing agent, builds its message list from a state seeded with a distinctive prior-session string and asserts the string is absent. |
| NEW-24 | **MEDIUM** | `llm.py:908-927` | `build_role_clients` short-circuits when the caller passes a concrete client instead of the router: the bench guard **and** the judge pin are both dropped, silently. | A script, a new CLI entry point, a replay/harvest tool or a web mode that builds one provider client to avoid failover passes a `GroqClient` in — every role including the judge now runs on a provider with no green bench artifact, with no refusal. Latent today; the guard is in the wrong place to survive a new caller. | Move the bench check into the judge-client construction path so it cannot be bypassed by the caller's choice of default client. |
| NEW-25 | **LOW** | `config.py:92`, `:218` | `COACH_ALLOW_UNVALIDATED_JUDGE=1` disables the ADR 0009 provider check entirely. ADR 0009 grants no such exemption. | A reader of ADR 0009 concludes a deployment's scores must be bench-comparable (the judge is pinned, no exceptions) and never thinks to check the environment for an override. | Either delete the flag, or have it log a loud, permanent warning and stamp "unvalidated judge" into every export and `TurnTrace`. |
| NEW-26 | **LOW** | `data/replay/deep-learning-strong.json:2` | The checked-in replay artifact carries a **version-0** Session state (no `schema_version`, no `language_mode`), and `load_replay_artifact` validates only the envelope version (`replay.py:174`), casting the state through unchecked (`:195`). | After a `schema_version` bump that changes how a key is read, `replay_decision` silently feeds the Supervisor an old-shaped state, and the replay bench reports the decision as a fair measurement. Adjacent to GH #113. | Validate the inner state version in `load_replay_artifact`, and regenerate the artifact. |
| NEW-27 | **LOW** | `docs/data-model.md:127`, `:133-135` | The doc states as fact that checkpoint readers "use `.get(\"schema_version\", 0)`; never subscript" and refuse higher versions. **No such reader exists** (QA-11). | An implementer bumping the schema reads the doc, believes rollback is already handled, and ships the bump without writing a reader — so a v1 image silently partially loads a v2 checkpoint. | Mark §4 of the doc as the intended contract, not the current state, until the reader exists. |
| NEW-21 | **LOW** | `App.tsx:171` | `cancel()` sends into a possibly-`CONNECTING` socket unguarded; the throw leaves `closingRef` latched. | Over TLS the 100–500 ms connect window leaves the Cancel button enabled (`App.tsx:323` has no `disabled`); pressing it throws and silently re-opens issue 0016. | Mirror `sendAnswer`: only send when `readyState === OPEN`; reset in a `finally`. |
| NEW-22 | **LOW** | `microloop.py:289` | Nothing compares a generated Follow-up against the one already asked — only against the seed. | The Interviewer can ask the same Follow-up twice in one question, burning a turn of the Candidate's budget. | Thread asked-so-far questions into `generate_follow_up` and extend `reject_reask`. |
| NEW-23 | **LOW** | `web_api.py:592` | `accept()` precedes the token check and nothing caps concurrent pre-auth sockets. | An unauthenticated attacker holds file descriptors and asyncio tasks for 10 s each, as fast as the loop accepts. | `limit_concurrency` on `uvicorn.run`; `limit_conn` in the nginx block. |

---

## 6. Plan to a stable milestone

Ordered by execution, not severity. "Parallel" marks work that touches disjoint files.

### M-0 — blocks the tag

| id | Do | Files | Verify | Est | Deps |
|---|---|---|---|---|---|
| M0-1 | Set `COACH_AUTH_TOKEN` and `COACH_ALLOWED_ORIGINS` in `.env`; delete the three `MIMO_*` keys; rotate the Groq key if it was ever shared | `.env` (operator, not in git) | `curl -s :8000/api/health` shows `"auth_required": true`; `curl` without a bearer on `/export.md` → 401 | 0.2 h | — |
| M0-2 | Refuse a fresh `start_session` on an id that already has a checkpoint — in-flight **and** completed; extend `cli.py:447-451` to the completed case too | `web_api.py`, `cli.py` | New test: start, complete, start again on the same id → `session_error`; assert `exports/<id>.md` md5 unchanged | 2 h | — *(parallel)* |
| M0-3 | Emit the friendly unknown-id message instead of streaming when `_checkpoint_values` is empty (port `cli.py:406-410`) | `web_api.py` | New test: `resume_session` on an unknown id → no `EmptyInputError` in the payload | 1 h | M0-2 (same function) |
| M0-4 | Bind answers to questions: carry `question_id` on `candidate_answer`, reject a mismatch | `web_api.py`, `microloop.py`, `web/src/lib/{types,api}.ts`, `App.tsx` | New test: double-send while Q1 pending → second frame refused; export shows each answer under its own question | 6 h | M0-2 *(parallel with M0-5..8)* |
| M0-5 | Make the telemetry counters per-Session (`ContextVar`, mirroring `_SESSION_ID` at `usage.py:264`) | `telemetry.py`, `evaluator.py` | New test: two threads, one dirtying the counter; assert the clean Session's `confidence` and `noise_events` are unaffected | 3 h | — *(parallel)* |
| M0-6 | Re-raise `AccountingUnavailable` at `supervisor.py:395`; add both typed stops to the `study_plan_node` and `postmortem` nets | `supervisor.py`, `postmortem.py` | New test per net: inject each exception, assert it propagates and no `failed` item is written | 2 h | — *(parallel)* |
| M0-7 † | Guard the panel calls; fall back to `_finalize(first, …, panel_suppressed=True)` | `evaluator.py` | New test: Skeptic raises `APIConnectionError` → the first-pass judgment survives, `stop_reason != "failed"` | 2 h | — *(parallel)* |
| M0-8 † | `evidence_weight_for`: `min(panel_agreement_weight, confidence_weight)` | `skill.py` | New test: degraded evidence + zero panel disagreement → weight capped by confidence. **Then `coach bench --k 3`** — this touches scoring | 1 h + bench | M0-7 |
| M0-9 | Validate the payload before `reserve_questions`; release the unused remainder at run end | `web_api.py`, `usage.py` | New test: 48 malformed starts leave `questions_today == 0`; a cancelled 10-question start releases 10 | 3 h | M0-2 |
| M0-10 | Fail closed on an unreadable/torn `.unreconciled` sidecar; log it | `usage.py` | New test: chmod the sidecar unreadable → `accounting_gate()` returns a blocking reason | 1.5 h | — *(parallel)* |
| M0-11 | Hold `_FAULT_LOCK` across write-and-mark; uuid-stamp faults and dedupe on replay | `usage.py` | New test: two threads flush one fault → exactly one sidecar row; `--reconcile` twice → tokens counted once | 3 h | M0-10 |
| M0-12 | `fcntl.flock` on both ledgers for the whole read-modify-write | `ledger.py`, `usage.py` | The two-process races in `/tmp` (this report's harness) → cap holds at 10, no lost Candidate record | 3 h | M0-11 |
| M0-13 | Allowlist bench-validated `(provider, model)` pairs; validate `base_url`; move the check into the judge-client construction path so a non-default client cannot bypass it (NEW-24); make `COACH_ALLOW_UNVALIDATED_JUDGE` log loudly and stamp every export | `config.py`, `llm.py` | New test: junk `OPENAI_MODEL` → startup refusal; a `GroqClient` passed to `build_role_clients` → refusal. Startup log names provider, model **and** base_url | 3 h | — *(parallel)* |
| M0-14 | Key the Skill ledger server-side (HMAC of token identity + name) and constrain `candidate_id` | `web_api.py`, `ledger.py` | New test: two clients using the same typed name get distinct ledger records | 4 h | — *(parallel)* |
| M0-15 | Add `pytest-timeout` and `timeout-minutes`; switch CI to `uv sync --locked --dev`; add `docker build .` + `docker compose config -q` jobs | `pyproject.toml`, `.github/workflows/ci.yml` | CI green on this branch; a deliberately hanging test fails instead of hanging | 1.5 h | — *(parallel)* |
| M0-16 | Push the branch, open the PR, let CI run, close GH #119 from it | — | CI green on the PR | 0.5 h | all above |

† Verification downgraded QA-06 and QA-07 to MEDIUM (the escalation precondition is measured dormant on
the production judge). They are ADR 0005 correctness, not data loss — **if you need to tag sooner, move
M0-7 and M0-8 to M-1** and save 3 h plus the bench run. Everything else in M-0 stays.

**M-0 total ≈ 37 h** (≈34 h without the two † tasks) plus one `coach bench --k 3` for M0-8.
**Eight tasks can start in parallel on day one**: M0-1, M0-2, M0-5, M0-6, M0-7, M0-10, M0-13, M0-14, M0-15. Only four chains are serial: M0-2→M0-3→(M0-9), M0-7→M0-8, M0-10→M0-11→M0-12, and M0-16 last.

M0-10 is the one to do first if you only have an afternoon: it is 1.5 h and it closes the only path where the **money** ledger fails open.

### M-1 — immediately after the tag

| id | Do | Files | Verify | Est |
|---|---|---|---|---|
| M1-1 | Client-side `maxLength` + counter; non-terminal error kind that keeps `currentQuestion` | `App.tsx`, `sessionReducer.ts` | vitest: an oversize answer does not wedge the composer | 2 h |
| M1-2 | Treat only `session_completed` as the end of the Session | `sessionReducer.ts` | vitest: the last `state_update` keeps status `evaluating` | 1 h |
| M1-3 | Atomic export write (temp + fsync + `os.replace`); checkpoint fallback before 404 | `exporter.py`, `web_api.py` | New test: ENOSPC mid-write leaves the previous file intact | 2 h |
| M1-4 | Scope `quota_retry` to the resuming session id | `usage.py` | New test: A's resume does not un-latch for B | 1.5 h |
| M1-5 | Sum all providers in `remaining_today`; failover multiplier in `worst_case_question_calls` | `usage.py` | New test: a failover call is counted against the daily rail | 2 h |
| M1-6 | Latch an accounting fault when a completion carries no parseable token count | `llm.py` | New test: a completion with no `usage` blocks the next metered call | 1.5 h |
| M1-7 | Process-level breaker registry keyed by provider | `llm.py` | New test: session B does not re-pay session A's retry storm | 3 h |
| M1-8 | Per-Session hard token ceiling at ~3× the admitted estimate | `usage.py` | New test: the rail fires near the admitted estimate, not 29× it | 2 h |
| M1-9 | Bench/forge preflight becomes a refusal; `start_refusal_reason` + `session_scope` on `postmortem`/`eval-harness`/`diagnose` | `cli.py`, `bench.py`, `forge.py` | New test: bench exits 2 when the day's budget is spent | 3 h |
| M1-10 | Re-raise the typed stops out of the per-case eval nets | `bench.py`, `forge.py`, `eval_harness.py` | New test: a quota death mid-bench exits 2 and writes **no** report | 2 h |
| M1-11 | Reject `COACH_ALLOWED_ORIGINS="*"` at startup | `web_api.py` | New test: `*` raises like a non-ASCII token | 0.5 h |
| M1-12 | Escape line structure in the Markdown export | `exporter.py` | New test: an answer containing `## Summary` cannot forge a section; regenerate goldens | 2 h |
| M1-13 | Render `failed` items to the Supervisor as `NOT ASKED (no evidence)` | `supervisor.py` | New golden: the prompt no longer shows `score=0.00` for a failed item | 1.5 h |
| M1-14 | Persist only Skills with `evidence_weight > 0` | `ledger.py`, `web_api.py`, `cli.py` | New test: an unprobed Skill leaves no ledger entry | 2 h |
| M1-15 | Clamp the mean / floor `prior_strength` in `_seed_prior` | `diagnostic.py` | Property test: `alpha > 0` and `beta > 0` for every (criticality, mean) pair | 1.5 h |
| M1-16 | `--resume` only when the checkpoint is not COMPLETE; in-flight guard on CLI resume | `cli.py` | New test: resume after completion refuses instead of re-reporting | 2 h |
| M1-17 | Render `item.error` for `failed` items; suppress the misleading 0.00/5 | `ReportView.tsx` | vitest for the `failed` branch | 1.5 h |
| M1-18 | Fix TLS renewal to webroot; fix the backup command's destination | `docs/deploy.md`, `docker-compose.yml` | Dry-run `certbot renew --dry-run` succeeds with nginx up | 2 h |
| M1-19 | Dedicated bounded executor for stale-thread joins | `web_api.py` | New test: N concurrent joins do not starve the default executor | 2 h |
| M1-20 | Stamp `schema_version` on every node return; add one reader that fails visibly | `supervisor.py`, `session_serde.py` | New test: a checkpoint with an unknown version refuses to resume | 2 h |

| M1-21 | Nest ledger records under `candidates` (flat-layout fallback) or reject `_meta` as a candidate id; add `UnicodeDecodeError` to the read guard | `ledger.py` | New test: `--candidate _meta` survives another Candidate's save; a non-UTF-8 ledger degrades instead of raising | 1.5 h |
| M1-22 | Write ADR 0006's own enforcement test: for each probing agent, build its messages from a state seeded with a distinctive prior-session string and assert absence | `tests/` | The new test fails if a transcript string reaches an Evaluator/Interviewer/Supervisor prompt | 2 h |
| M1-23 | Mark `docs/data-model.md` §4 as the intended contract until a reader exists; re-pin the three `AUDIT.md` lines (QA-17) | `docs/data-model.md`, `AUDIT.md` | The docs no longer describe readers that do not exist | 0.5 h |
| M1-24 | Validate the inner state version in `load_replay_artifact`; regenerate `data/replay/deep-learning-strong.json` | `replay.py`, `data/replay/` | New test: a version-0 inner state is refused; `pytest tests/test_replay.py` green | 1.5 h |

**M-1 total ≈ 44 h.**

### M-2 — accepted debt, not blocking

| id | Item | Why deferred |
|---|---|---|
| M2-1 | Split `web_api.py` (1,122) and `cli.py` (1,246) | Pure restructuring; `tests/test_serde_golden.py` and `tests/test_cli.py` are the contracts that make it safe later. No user-visible defect. |
| M2-2 | SQLite read path for the usage ledger (3–4 full parses per graph event) | Trivial at today's 1,431 rows; becomes a cliff only after sustained pilot use. Pair it with rotation. |
| M2-3 | Ledger rotation | Same trigger as M2-1. |
| M2-4 | Per-record ownership / accounts (GH #84) | This milestone is explicitly a **trusted pilot**; ownership is a public-launch gate (`docs/issues/README.md:33-36`). M0-14 removes the accidental-collision half. |
| M2-5 | Skill-ledger history (blocks dashboard #83) | M3 work; needs the storage decision, not a patch. |
| M2-6 | The 16 remaining §3.3 duplications + §3.5/§3.7 patterns | Maintainability only; no failure scenario. |
| M2-7 | `SelfCritiqueTrace`, `docs/reference/*`, `data/` write-only outputs | Dead weight, zero risk. |
| M2-8 | `resources.py:3` stale comment + decide Chroma-or-delete for the resources half | One-line comment fix now; the wire-or-delete decision belongs with R-13. |
| M2-9 | `ruff format` (18 files) | One mechanical commit; do it when no PR is in flight. |
| M2-10 | Follow-up re-ask guard; `skip_ahead` seed gate; sticky `concept_miss` | Loop-quality polish; each wastes a turn but corrupts nothing. |

---

## 7. Definition of "stable" for this milestone

Every line is one command with a binary answer. Tag only when all are true.

| # | Check | Command |
|---|---|---|
| 1 | Lint clean | `uv run --no-sync ruff check --no-cache` → exit 0 |
| 2 | Types clean | `uv run --no-sync mypy` → "no issues found in 33 source files" |
| 3 | Suite green, twice, no flake | `timeout 300 uv run --no-sync pytest -q -p no:cacheprovider` twice → same count, exit 0 |
| 4 | No test can hang | `pytest-timeout` in `pyproject.toml` **and** `timeout-minutes` on both CI jobs |
| 5 | Lockfile honest | `uv sync --locked --dev` → exit 0 |
| 6 | Web gates green | `cd web && npm run lint && npx tsc -p tsconfig.app.json --noEmit && npx vitest run && npm run build` → all exit 0 |
| 7 | Wire format frozen | `timeout 300 uv run --no-sync pytest -q -p no:cacheprovider tests/test_serde_golden.py` → exit 0 |
| 8 | Judge untouched, or re-benched | `git diff <tag-base>..HEAD -- src/interview_coach/evaluator.py src/interview_coach/rubric.py data/bench/` empty — **or** a `coach bench --k 3` report at the production temperature in `docs/audits/` |
| 9 | Image builds from a clean tree | `git archive HEAD \| tar -x -C /tmp/ctx && docker build -t coach:tag /tmp/ctx` → exit 0 |
| 10 | Container serves as uid 10001 | `docker run … && curl -s :8000/api/health` → `"status":"ok"`, `"auth_required":true`; `docker exec … id` → uid=10001 |
| 11 | Auth enforced | `curl -o /dev/null -w '%{http_code}' :8000/api/sessions/x/export.md` → 401 |
| 12 | A whole Session completes in the container | drive `start_session` → answers → `session_completed`; `/app/state/exports/<id>.md` exists |
| 13 | State survives container replacement | `docker rm -f` the container, start a new one on the same volume → export md5 unchanged, endpoint 200 |
| 14 | Quota inside a question suspends cleanly | `pytest tests/test_supervisor.py -k dead_quota_mid_session` → exit 0 (`question_count` unchanged, no `failed`, no Skill update) |
| 15 | Two starts racing admit at most one | the two-**process** race harness → `questions_today` ≤ cap |
| 16 | Resume does not recharge a start reservation | `pytest tests/test_usage.py -k resume` → exit 0 (`reserve_questions` is on the `not resume` branch, `web_api.py:833`) |
| 17 | Bounds hold at the wire | the probe script: oversize answer / elapsed / max-questions / non-object frame / queue flood all refused, session not wedged |
| 18 | Reusing a Session id cannot destroy a report | start on a completed id → `session_error`; export md5 unchanged |
| 19 | Resume of an unknown id is friendly | `resume_session` on a fresh id → no `EmptyInputError` in the payload |
| 20 | An answer cannot be scored against the wrong question | double-send probe → second frame refused; export shows each answer under its own question |
| 21 | Operator config is set | `/api/health` `"auth_required": true`; `.env` has no `MIMO_*` |

**Explicitly NOT included in this milestone** — state these on the tag:

- **No per-user authentication or per-record ownership.** One shared token gates the whole installation. Any token holder can resume, cancel or export any Session id they can guess or obtain. This is a **trusted pilot**, not a public deployment (`docs/issues/README.md:33-36`).
- **No durable per-turn ACK.** Resume granularity is the question, not the turn: an answered Follow-up inside an unfinished question is lost on a crash. That is M1/F4.
- **No Skill-ledger history** — one snapshot per Candidate, so no progress dashboard (#83).
- **No live judge-quality evidence in CI.** The judge is exercised only through fakes; the real gate stays the manual `coach bench --k 3`. Bilingual fairness is a separate gate (`docs/issues/README.md`, Q2).
- **No load, latency or cost SLO.** The daily cap is 480 questions for the *whole deployment* (one bucket keyed on `sha256(token)[:16]`), i.e. ~48 ten-question Sessions/day across all users.
- **No browser E2E in CI.** The Playwright specs need a live backend and were not run.

---

## 8. Residual risk after M-0

| Risk | Why it survives M-0 | How you will notice |
|---|---|---|
| A reconnect during a real provider stall blocks up to 120 s | **Measured**: one unreachable provider costs 4 × 60 s attempts plus backoff ≈ 4.2 min, longer than `STALE_RUNTIME_JOIN_SECONDS`. The Candidate is told to retry and may retry-storm | Repeated `"The previous run of this Session is still finishing"` in the log, clustered on one session id |
| Two processes on one checkpoint `thread_id` | M0-12 locks the two ledgers, not the checkpoint SQLite. `coach session --resume` against a live web Session is still possible (NEW-20) | Interleaved or duplicated transcript items; `started_at` jumping backwards in the export |
| A cross-session evidence leak I have not found | M0-5 fixes the telemetry counter, but `usage._FAULTS`, `_PROVEN_WRITABLE` and `LLMRouter._breakers` are also process-global mutable state shared by every Session thread | A Candidate's `confidence`/`noise_events` that no single Session explains; `evidence_weight` inconsistent with the visible transcript |
| Spend invisible to every rail | M1-6, not M0. A gateway that renames or omits `usage` records zero tokens and latches nothing (NEW-07) | `coach usage` totals far below the provider's own dashboard |
| The judge silently moves | M0-13 gates the model string at startup, but nothing detects drift *within* a pinned model, and CI never calls the judge | Bench scores moving with no code change — only visible if you actually run `coach bench --k 3` |
| A truncated export served as complete | M1-3, not M0 | A 200 OK report that ends mid-sentence; `_persist_export` OSError lines in the log |
| `.env` holds a live Groq key for a non-bench-validated provider | M0-1 removes the MiMo keys; Groq stays as the availability fallback | Judge-role traffic on `groq` in the `llm-call` trace — which must never happen (ADR 0009 addendum a) |
| The 8-deep answer queue drops silently past the bound | Verified visible today (`"Answer dropped…"`), but the drop is reported as a `session_error`, which the client treats as terminal | Candidates reporting the Session "died" right after typing fast |

---

### Appendix — what was executed for this report

Gates: `ruff check --no-cache`; `mypy` (cache outside the repo); `pytest -q -p no:cacheprovider` ×3 at
HEAD and once at each of the 8 commits; `npm run lint`; `tsc -p tsconfig.app.json --noEmit`;
`vitest run`; `npm run build`; `ruff format --check`.

Isolation: 17 detached `git worktree`s under the session scratchpad; every revert-test ran with
`PYTHONPATH` pointed at its own worktree so the editable install could not mask it. The primary repo was
never written to.

Runtime: `docker build` from `git archive HEAD` (402 MB, exit 0); containers on disposable volumes driven
through real WebSocket clients for demo completion, reconnect, duplicate connection, input bounds, queue
flood, answer/question misbinding, session-id reuse, unknown-id resume, and a quota-dead stub provider.
Two-process races for the usage ledger reservation. No real provider was ever called.

Not executed: `docker compose up` with nginx/TLS (certs are untracked); Playwright E2E; any live judge
call; `coach bench`.
