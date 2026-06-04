# Supervisor + LangGraph migration

**Type:** AFK

## What to build

The **Macro-loop** and the move to LangGraph (see `ADR 0001` and `ADR 0004`). Build the **Supervisor** as a plan-executor over the **Topic Plan**: by default it walks the plan, and it makes a single LLM-judged decision per resolved question — whether emerging Skill evidence justifies *deviating* (extra question, skip ahead, switch Skill, end early). Hard caps (max questions, max time) are deterministic rails. Then migrate the hand-rolled Python orchestration from earlier slices into a LangGraph `StateGraph` over a single session state, with `SqliteSaver` checkpointing (resume by session id) and a `draw_mermaid_png()` architecture diagram. Agents don't change — only the wiring.

## Acceptance criteria

- [x] After a resolved question the Supervisor either advances the plan or deviates, and logs the LLM reasoning for deviations
- [x] A consistently strong Candidate triggers early termination; a struggling one triggers more probing or a Skill switch
- [x] Hard caps bound the session regardless of the LLM's choices
- [x] A multi-question session runs through the StateGraph and can be resumed mid-session from the SqliteSaver checkpoint by session id
- [x] The architecture diagram exports to an image file

## Done

- Added `interview_coach.supervisor` with a thin Supervisor over the Topic Plan, hard `max_questions` / `max_elapsed_seconds` rails, typed `SupervisorDecision`, and LangGraph `StateGraph` wiring over one `SessionState`.
- Added `SqliteSaver` checkpoint support keyed by `session_id` (`thread_id`), including a resume path that can continue from a mid-Session checkpoint.
- Added `draw_mermaid_png()` export through `export_architecture_diagram()` and `coach session --diagram`.
- Added `coach session` to run or resume the multi-question Session through the graph.
- Added minimal non-`ml_fundamentals` seed questions so the Topic Plan can be executed before issue 0013 expands the bank.
- Live smoke found and fixed a scripted-Candidate bug: Session now caps each Micro-loop to the seed's available scripted answers, so a one-answer fixture stops by safety cap instead of crashing on a Follow-up.

### Post-audit hardening (live MiMo audit)

- **Seed gate (deviation honesty):** the Supervisor can no longer `extra_question` / `switch_skill`
  onto a Skill with no unused seed — a validator rejects it and the model re-picks `advance_plan` /
  `end_early`. A **SEED AVAILABILITY** block in the prompt makes the choice informed. Added
  `seeds.seed_count()` and `supervisor._attempts_by_skill()`. Previously a deviation on a single-seed
  Skill re-asked the byte-for-byte same question with the same scripted answer (zero new evidence).
- **Seed bank widened:** `deep_learning` / `mlops` / `system_design` / `vietnamese_nlp` now carry ≥2
  distinct seeds with ≥2 scripted answers each, so a probe can resolve after a Follow-up instead of
  always tripping the safety cap, and `extra_question` rotates to a genuinely different question.
- **Crash fix:** added the missing `deep_learning` seed concept note — a Follow-up on `deep_learning`
  was calling `lookup_concept(skill='deep_learning')`, which hard-raised `LookupError` and killed the
  whole Session. Added a regression test asserting every canonical Skill has a seed concept note.
- **`coach session` concept flags:** `--concept-store` / `--concept-persist-dir` / `--no-seed-concepts`
  (parity with `coach interview`), threaded into the graph's Micro-loop.

## Verified

- `uv run pytest` -> 93 passed, 6 deselected.
- `uv run ruff check .` -> all checks passed.
- `uv run pytest -m live` -> 5 passed (incl. a new `@pytest.mark.live` Session test against MiMo).
- `uv run coach session --max-questions 4 --target-role "machine learning engineer" --claim ml_fundamentals=4 --claim mlops=2`
  -> live MiMo Session completed through LangGraph across four **distinct** Skills
  (`ml_fundamentals` → `mlops` → `deep_learning` → `system_design`), no verbatim repeats, Follow-ups
  grounded in concept notes, Supervisor reasoning citing seed availability; `max_questions` ended it.
- `uv run coach session --diagram ...` -> exported a PNG architecture diagram.

## Status

**Closed — no MVP blocker.** One robustness gap was spun off, not blocking: the Session has no
per-question failure isolation, so a single agent/provider hiccup (e.g. a transient malformed MiMo
tool name) aborts the whole run — tracked in **issue 0014**.

## Blocked by

- 0006 (reflection in the micro-loop)
- 0007 (tool-using Interviewer)
- 0009 (Topic Plan to execute)
