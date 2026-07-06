# Question-pack platform + first VN company-style pack

**Type:** HITL
**Kind:** enhancement

## What to build

The bank is the product's confirmed top content risk: 15 questions total, and because per-Skill
attempt counts reset each Session, a returning Candidate gets the *identical questions in the
identical order* every time — they memorize the bank in 1–2 sessions. Separately, the Topic
Plan's `target_difficulty` never influences question selection at all (adaptivity is currently
decorative).

Invert engine/content per ADR 0008:

- A public **pack directory spec** — questions + concept notes + metadata (role, company style,
  difficulty tags) — with the built-in bank as the reference pack.
- **`coach pack lint <dir>`** reusing the bank loader's fail-loud cross-referential validation.
- **`--pack <dir>`** loading on `coach session`.
- Ship **one real VN company-style pack** (~20 questions, FPT-style: process-heavy OOP/SQL plus
  an English self-introduction item), researched from public interview reports.
- While in the selection code, fix both latent bugs: make `target_difficulty` actually drive
  question choice, and vary rotation across repeat Sessions so returning users see fresh
  questions.

HITL because pack content quality and difficulty calibration are human judgment (same reasoning
as issue 0013, whose breadth tail effectively becomes pack authoring under this contract).

## Acceptance criteria

- [ ] Pack spec documented; `coach pack lint` validates schema + cross-references and dies loudly
      with a named violation on a bad pack
- [ ] `coach session --pack <dir>` runs entirely from the pack; the default bank keeps working
      unchanged as the reference pack
- [ ] `target_difficulty` influences selection — test: same Topic Plan, different targets ⇒
      different questions chosen
- [ ] A returning Candidate does not get the identical question sequence (rotation aware of
      session history; integrates with the ledger id when 0023 lands, but must not require it)
- [ ] The FPT-style pack ships with ≥20 lint-clean questions including the EN self-intro item

## Blocked by

- ADR 0008 (the contract decision). Related: 0013 (its remaining breadth tail should be authored
  as pack content once the contract exists — do not close 0013 from here).

## Status

**Open.**
