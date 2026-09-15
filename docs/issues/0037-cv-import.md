# JD text first; CV import deferred → Diagnostic setup

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#86](https://github.com/nekloyh/get-hired/issues/86) (R-31)

## What to build

This slice is split under the [implementation plan M3](README.md#m3--finish-the-repeat-practice-loop-personaltrusted-pilot).
Keep #86 as the tracker: a bounded text input adapter first, document upload only after evidence
of demand. The existing Diagnostic already consumes claims + `target_role` + `target_companies`.

### First increment: JD text

- Paste bounded JD text → one single-shot extraction call producing a validated draft of
  role/company/requirements mapped to the existing taxonomy. Treat document instructions as
  untrusted input, not instructions to the agent. No new tool grant (ADR 0003).
- Candidate confirms/edits the setup before starting. A JD describes the employer's requirements,
  **not the Candidate's competence**: never convert JD requirements into claimed mastery or stronger
  confidence. Personal claims remain separately entered; use the existing Diagnostic seam.
- Unknown roles/requirements are visible as unmapped; no silent promise of new Skill support.
  Preserve manual setup when extraction fails. Use M0 input/budget rails.

### Deferred increment: CV upload

The original PDF/text CV extraction remains follow-on scope: extract draft personal claims and
suggested role/company, confirm/edit before diagnosis, preserve weak-prior semantics. Resume only
when JD utility is established and file validation, retention/delete, and the relevant access
boundary are specified. This plan does not authorize PDF parsing, audio or CV storage in M3.

## Acceptance criteria — JD text increment

- [ ] E2E: paste fixture JD → confirm/edit draft → text Session runs using the existing Diagnostic.
- [ ] Invalid/oversized/instruction-injection fixtures cannot bypass limits, modify scoring policy,
      or silently invent Candidate claims; schema failure shows a notice and retains manual setup.
- [ ] Identical personal claims with/without a demanding JD preserve weak-prior invariants; role
      criticality may change sanctioned prior strength/coverage, never personal prior mean.
- [ ] No new tool grant: extraction call is single-shot, with no tools parameter.
- [ ] Unsupported role/Skill requirements are shown for correction instead of silently treated as
      a supported pack. Resume preserves confirmed setup and pack.
- [ ] Log/eval artifacts omit private JD text; retention/delete follows M3 (and M4 before public).

## Deferred CV acceptance criteria

When resumed: fixture PDF/text upload → editable claims; malformed files fail visibly; maximum
CV claims have the same weak priors as equivalent manual claims; no tool grant. Add file-specific
limits, sensitive-data retention and applicable ownership tests before accepting uploads.

## Blocked by

- M2 quality/trace gates and M0 input/budget limits; no accounts/Postgres prerequisite for a
  personal/trusted-pilot JD text form under the documented shared trust boundary.
- M4 ownership and data controls before public exposure. CV upload requires its own later gate.

## Status

**Open in the local plan; remote status not refreshed.** Reordered 2026-09-13: JD text is P1/M3;
CV upload is P2/deferred. #86 remains the tracker; no duplicate issue is created.
