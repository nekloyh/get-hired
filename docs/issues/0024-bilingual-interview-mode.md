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

- [x] `language_mode` threads end-to-end: CLI flag + web control → Interviewer asks in the right
      language/mix → Evaluator instructed per mode → export records the mode
- [x] `english_delivery` is scored only on English answers; technical dimensions proven
      language-independent on the bench's EN/VN paired cases (deltas within a stated tolerance)
- [x] Weak-delivery feedback includes ≥3 concrete phrase fixes
- [x] Bench (0022) extended with mixed-mode cases; the regression gate stays green
- [x] A pure-VN Session simply never activates `english_delivery` — no phantom scores

## Blocked by

- 0022 (VN judge quality must be measured before scores steer anything)
- ADR 0007 (the state-threading and separation decision)

## Status

**Closed.**

### Done

- `language.py`: `language_mode` vocabulary (`en|vn|mixed`), a deterministic Vietnamese-character
  detector (`answer_is_english`, ratio-based, NFC-folded), and `rubric_with_delivery` — activation
  of `english_delivery` is deterministic per answer, never the judge's call, so a `vn` Session
  structurally cannot grow phantom delivery scores.
- `english_delivery` joined `DIMENSIONS` with BARS-style guide anchors, but is excluded from
  `linear_weighted_score` and (by prompt contract) from the judge's holistic `weighted_score` —
  the Beta skill posterior moves on technical evidence only (ADR 0007). A delivery-only rubric is
  rejected outright.
- `Evaluation.delivery_fixes` + validator: an `english_delivery` score ≤ 3 must carry ≥ 3 concrete
  phrase-level fixes (each quoting the candidate's actual wording); fixes are forbidden when the
  dimension is inactive.
- Threading: CLI `--language`, web `StartSessionPayload.language_mode` → `SessionState` →
  `question_node` → `run_micro_loop` → `evaluate(language_mode=...)` + Interviewer prompts
  (`vn`/`mixed` blocks ride the user turn; the `en` prompt stays byte-identical to pre-0024) →
  Study Planner (plan text in Vietnamese for vn/mixed; `english_delivery` excluded from technical
  gap mining) → export Summary records the mode.
- The Interviewer renders bank seed questions into the Session language for vn/mixed
  (`render_seed_question`, one extra call, degrades to the EN original on failure) and generates
  follow-ups in-language (a deterministic validator rejects an all-English follow-up in `vn` mode).
- Bench: `BenchCase.language_mode` (legacy cases stay `en` — byte-stable prompts), four mixed-mode
  cases including the disentanglement proof (`mixed_ml_leakage_broken_english`: strong technical
  content in broken English), an `english_delivery` anchor, and a mixed-mode report section.
- Live gate (ADR 0009): `docs/audits/calibration-bench-2026-07-11-bilingual-mode.md` — all four
  mixed cases in band; the broken-English case scored technical 4.00 with english_delivery 2/2
  (judge matches the human label) and 3 phrase fixes; EN/VN paired deltas mean |Δ| 0.22.

## Continued by (2026-07-19 remediation)

- Toneless-Vietnamese misclassification in answer_is_english (diacritic-ratio detector): R-23 (GH #78).
