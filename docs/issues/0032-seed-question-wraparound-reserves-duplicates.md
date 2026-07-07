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

- [ ] Selecting past a Skill's seed count either signals exhaustion (so the caller can skip/stop that
      Skill) or is provably unreachable given the Topic Plan construction — documented either way
- [ ] A test covers attempts ≥ `seed_count` for one Skill

## Blocked by

None.

## Status

**Open.**
