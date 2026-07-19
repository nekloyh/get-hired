# CV/JD import → Diagnostic priors

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#86](https://github.com/nekloyh/get-hired/issues/86) (R-31)

## What to build

Resume/JD import personalizing the interview is table-stakes across every 2026 competitor
(Final Round, Verve, Sensei, Yoodli — panel report Phần 3). In this architecture it is an *input
adapter*, not a new subsystem: the Diagnostic already consumes claims + `target_role` +
`target_companies`.

- Upload CV (pdf/text) → **one single-shot extraction call** producing a validated schema of
  claims + suggested `target_role`/companies. Per ADR 0003 this is NOT a new tool-using agent —
  single-shot with the document injected into the prompt.
- The Candidate **confirms/edits** the prefilled setup form before the Session starts — extraction
  output is a draft, never silently trusted.
- The confirmed values flow through the **existing Diagnostic seam**. ADR 0002 invariant stated in
  the UI copy and enforced by the existing prior tests: a CV claim is a *claim* — priors stay
  weak, the claim sets starting difficulty, never our confidence.

## Acceptance criteria

- [ ] e2e: upload a fixture CV → setup form prefilled → Candidate edits one claim → Session runs.
- [ ] Extraction schema unit tests (malformed pdf/text degrade to an empty form + visible notice,
      never a crash — ADR 0005 classification: infrastructure degrade).
- [ ] Prior-weakness invariant test: a maxed-out CV ("expert in everything") produces the same
      weak-prior strength as manual claims of 5 — no new prior-inflation path.
- [ ] No new tool grant (ADR 0003 addendum): the extraction call is single-shot, verified by the
      absence of any tools param in its request construction.

## Blocked by

- Wave 1 security (R-06/#61, R-07/#62) — uploads are user data; do not accept them on an
  unauthenticated surface.

## Status

**Open.** Spec'd 2026-07-19 from the panel review market table-stakes + remediation R-31;
scheduled Later (Wave 3).
