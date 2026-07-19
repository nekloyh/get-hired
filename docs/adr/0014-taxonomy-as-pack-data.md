# The Skill taxonomy, role criticality, and correlations are pack data

**Status: Proposed — gated on experiment E6. Not applied to code until Accepted.**

(Numbering note: 0012–0013 are intentionally reserved for the experiment-gated follow-ons already
named in the 2026-07-19 red-team review — the E3 grounding standardization and the E5 escalation
cutover — if they graduate to standalone ADRs; this ADR keeps the number that review assigned it.)

Question packs (ADR 0008) grow three new declarative sections — `skills`, `criticality`,
`correlations` — and the engine derives its Session-scoped taxonomy from the loaded pack instead
of from code constants. `coach pack lint` validates the sections fail-loud; the web UI renders the
Skill list dynamically.

## Why

ADR 0008's own manifesto — content shapes behavior "**through data, never through code changes**"
— is only half-implemented. Verified on 2026-07-19:

- `SKILLS` is a hardcoded 5-tuple (`diagnostic.py:22-28`); the web UI hardcodes the same five
  (`web/src/lib/types.ts`).
- Role criticality knows exactly **three** role strings (`diagnostic.py:118-140`); any other
  `target_role` — "data engineer", "NLP researcher" — silently falls back to all-PERIPHERAL,
  which mis-prioritizes every probe with no warning.
- Company criticality knows three companies (`:142-146`); correlations are a hand-built code
  table (`:154-160`).

Consequence: a pack **cannot** ship a new Skill, role, or company today. The FPT pack had to
squeeze OOP/SQL content into the five ML skills (issue 0025's own admission). Every new
interview domain is a code change — exactly what ADR 0008 promised to end.

## Design under trial

- `pack.yaml` sections: `skills` (id, display name), `criticality` (role/company → skill tier),
  `correlations` (pairwise prior-transfer weights — still **prior-only**, ADR 0002 unchanged).
- Missing sections default to today's built-ins (zero-change rollout for existing packs); an
  *unknown role with no criticality entry* becomes a loud lint warning instead of a silent
  all-PERIPHERAL.
- Supervisor rails are already bank-parameterized (`seed_count(skill, bank=...)`) — the seam is
  half-built; the remaining consumers are the Diagnostic tables and the web Skill list.

## Gate

**E6:** author a second pack declaring one genuinely new Skill; behind a flag, run lint + one full
scripted Session + the replay bench + the Supervisor rails tests. *Win:* lint rejects malformed
sections with named violations, the Session runs end-to-end on the new Skill, the UI renders it
without a code change, and no rails/replay regression. *Lose:* the seam demands per-Skill code
after all — record where, and this ADR is Rejected in favor of documented code-side extension
points.

## Considered Options

- **Grow the code tables as needed** (status quo): rejected — re-couples every content domain to
  a repo commit, and the silent all-PERIPHERAL fallback is a correctness bug, not just an
  inconvenience.
- **Full plugin system (Python entry points per pack):** rejected — packs are data by ADR 0008;
  executable packs reopen the trust boundary lint exists to close.

*Source: ADR red-team review 2026-07-19 — verdict REAFFIRM 0008 contract + AMEND scope (the
manifesto's unimplemented half); panel report Phần 2 (criticality table findings).*
