# Cross-session memory is decayed Bayesian priors, not transcript RAG

The coach remembers a returning **Candidate** by persisting per-Skill Beta posteriors when a
Session completes and re-seeding the next Session's priors from them, with exponential
pseudo-count decay by days elapsed, injected through the Diagnostic's existing prior seam
(the injection point ADR 0002 sanctions). We do **not** retrieve prior transcripts into prompts
as "memory".

## Why

ADR 0002 already establishes the two invariants this preserves: priors are where outside knowledge
enters, and direct evidence must dominate quickly. Decayed posteriors keep cross-session memory as
auditable, offline-testable arithmetic — independent of provider quality and prompt phrasing.
Decay states the epistemics honestly: old evidence is weaker evidence, so a Candidate who was
strong three months ago starts warmer than a stranger but is still probed.

Transcript-RAG memory was rejected because it is unfalsifiable (there is no way to assert what the
model actually used), grows unboundedly, couples memory quality to retrieval quality, and
reintroduces exactly the masked-gap failure ADR 0002 was written to prevent: stale strong-sounding
text softening the probing of a Skill that has since decayed — the worst failure for a tool whose
job is finding gaps.

## Considered Options

Storing raw past evaluations and replaying them into the new Session was considered and rejected:
it is mathematically equivalent to decayed priors with a specific decay schedule, but with more
moving parts and a schema-migration burden on every `Evaluation` change.

## Addendum (2026-07-19): the boundary is probing-vs-presentation, not "no memory"

The scoring invariant above was independently re-derived and **stands**: 2026 long-context models
do not fix unfalsifiability (there is still no way to assert what the judge actually used), and the
masked-gap failure is unchanged. But the original text conflates the *channel* (judge prompts) with
the *capability* (memory in general), and that conflation forbids a legitimate product feature.
The precise boundary:

- **Probing & judging surfaces** — Evaluator, Interviewer, Supervisor, and Diagnostic priors
  beyond the decayed Beta — **never** see prior-session transcripts or summaries of them. A
  remembered strong answer softening a follow-up is the same masked-gap failure as a softened
  score. This is the invariant, unchanged.
- **Presentation & planning surfaces** — the UI, exports, and the Study Planner's *narrative*
  output — **may** consume session history ("last time you struggled with backpressure; here is
  the delta"). Transcripts already persist in checkpoints and exports; showing the Candidate their
  own history judges nothing and softens no probe. This is **coaching memory** (see CONTEXT.md),
  and issue 0035 (GH #83) is its consumer.

Enforcement is testable without trusting anyone's discipline: prompt-construction unit tests
assert that no prior-session transcript text enters the message lists built for the three probing
agents. A violation is a red test, not a code-review catch.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM invariant + AMEND (carve-out); panel
report Phần 3 (competitors ship longitudinal views; the differentiator "longitudinal skill state"
is invisible without a presentation surface).*
