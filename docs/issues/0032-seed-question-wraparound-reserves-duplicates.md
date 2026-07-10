# Seed-question selection wraps around and re-serves a duplicate past the seed count

**Type:** AFK
**Kind:** bug (minor)
**Tracked on GitHub:** [#36](https://github.com/nekloyh/get-hired/issues/36)

## What to build

Found reviewing the Wave B adaptive-selection code. `select_seed_question` (`seeds.py`) indexes with
`order[question_number % n]`, so attempts `0..n-1` give distinct prompts but attempt `n` onward
silently re-serve an already-asked question instead of signalling exhaustion.

In practice the Supervisor's seed gate (`_has_unused_seed`, `supervisor.py`) prevents *choosing*
`extra_question` / `switch_skill` beyond a Skill's seed count, so the common paths are safe. The gap
is a Topic Plan that lists the same Skill in **more entries than it has seed questions** — each entry
drives a fresh `question_node`, and nothing stops selection from wrapping back to a duplicate prompt.

Low severity: the outcome is a repeated question, not a crash or a wrong score. But it defeats the
duplicate-avoidance intent of the rotation logic.

## Acceptance criteria

- [x] Selecting past a Skill's seed count either signals exhaustion (so the caller can skip/stop that
      Skill) or is provably unreachable given the Topic Plan construction — documented either way
- [x] A test covers attempts ≥ `seed_count` for one Skill

## Resolution

Both, belt-and-braces. `select_seed_question` now raises `SeedQuestionsExhausted` (a `LookupError`)
for attempts ≥ `seed_count` instead of `order[question_number % n]` silently wrapping to a duplicate
(`seeds.py`). It is also **provably unreachable** in a well-formed run: the diagnostic validator
forbids a Skill appearing twice in a Topic Plan (`diagnostic.py` `check_plan`), and the Supervisor's
`_has_unused_seed` gate keeps dynamic deviations strictly under `seed_count` — so the raise is a loud
backstop, not a hot path. To make that backstop safe, `question_node` now performs seed selection
*inside* its slice-0014 failure-isolation net, so an over-subscribed plan is recorded as a visible
`FAILED` question and the Session advances — never a re-served duplicate, never a crash.

Covered by `tests/test_seeds.py` (attempts ≥ `seed_count` raise for every Skill; attempts `0..n-1`
stay distinct; difficulty ordering and rotation preserved) and
`tests/test_supervisor.py::test_seed_exhaustion_is_isolated_as_a_failed_question_not_a_duplicate`.

## Blocked by

None.

## Status

**Closed.**
