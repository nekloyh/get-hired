# Bilingual VN/EN interview mode with disentangled English scoring

**Type:** AFK
**Kind:** enhancement

## What to build

Real Vietnamese interviews code-switch (VN conversation with EN terms, or a full EN round inside a
VN process); today the Session's language is implicit and the judge can conflate an
English-communication gap with a knowledge gap — poisoning the skill state with the most common
misread of VN fresh grads. Per ADR 0007:

- Session-level **`language_mode`** (`en` | `vn` | `mixed`) chosen at setup — a `--language` CLI
  flag and a web setup control — threaded through the Session state into the Interviewer and
  Evaluator prompts. `mixed` means natural code-switching like a VNG/FPT round.
- A sixth rubric dimension **`english_delivery`**, active only when the answer is in English
  (weight-0 disable otherwise — the existing rubric mechanic), so English quality is scored
  *apart from* the five technical dimensions.
- Feedback for weak delivery names **concrete phrase-level fixes** (at least three), not "improve
  your English".

The main risk — judge quality in Vietnamese on the current provider — is exactly what the
calibration bench measures, which is why this sequences after 0022.

## Acceptance criteria

- [ ] `language_mode` threads end-to-end: CLI flag + web control → Interviewer asks in the right
      language/mix → Evaluator instructed per mode → export records the mode
- [ ] `english_delivery` is scored only on English answers; technical dimensions proven
      language-independent on the bench's EN/VN paired cases (deltas within a stated tolerance)
- [ ] Weak-delivery feedback includes ≥3 concrete phrase fixes
- [ ] Bench (0022) extended with mixed-mode cases; the regression gate stays green
- [ ] A pure-VN Session simply never activates `english_delivery` — no phantom scores

## Blocked by

- 0022 (VN judge quality must be measured before scores steer anything)
- ADR 0007 (the state-threading and separation decision)

## Status

**Open.**
