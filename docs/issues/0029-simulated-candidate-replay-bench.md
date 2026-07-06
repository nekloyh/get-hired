# Simulated Candidate + Supervisor replay bench

**Type:** AFK
**Kind:** enhancement

## What to build

The 154-test suite runs 100% against fakes, and nothing anywhere evaluates the *loop* — whether a
whole Session converges on the truth about a candidate. Close the eval stack: the calibration
bench (0022) calibrates the judge; this calibrates the orchestrator.

- A **persona-driven LLM Candidate** with a ground-truth mastery profile (e.g. "strong
  deep_learning, weak mlops, rambles when unsure"), plugged into the existing Candidate seam the
  scripted fixture uses today.
- A runner drives a **full unattended Session** (offline graph; live judge optional) and asserts
  **trajectory properties**, not per-call outputs: the final posterior mastery *ordering* matches
  the persona's ground truth, and the Supervisor terminates early on the persona's strong Skill
  instead of burning budget there.
- Dump the checkpointed trajectory as the first **versioned replay artifact**, and re-run the
  Supervisor's decision node over it with a different model as the counterfactual demo — the
  seed of decision-level regression testing.

## Acceptance criteria

- [ ] ≥1 persona Candidate completes a full Session unattended through the existing seam
- [ ] Trajectory assertions pass: posterior ordering vs ground truth; early-termination on the
      strong Skill
- [ ] The trajectory checkpoint is saved as a versioned replay artifact, and the decision node
      can be re-run over it in isolation (counterfactual model swap demoed once)
- [ ] Documented alongside 0022 as the two halves of the eval stack (judge calibration + loop
      calibration)

## Blocked by

- 0015 (a live judge is needed for the meaningful closed-loop run; the persona + assertions can
  be developed against fakes first)

## Status

**Open.**
