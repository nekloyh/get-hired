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
