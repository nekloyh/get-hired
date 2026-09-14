# Giấy Dó & Mực Đỏ — the web app's brand system (issue: FE redesign, 2026-07-11)

The metaphor is the Vietnamese teacher's desk: the interview is a graded exam, and the product's
one chromatic voice is the teacher's red pen (bút đỏ). Chosen after a competitive color audit —
every interview-prep brand is cold blue/purple/amber SaaS; warmth, paper, and cultural specificity
were unclaimed territory (research: two-ink systems win awwwards 2025–26; no winner uses an AI
gradient).

## Tokens

| token | value | role |
| --- | --- | --- |
| `--paper` | `#f6f1e5` | rice-paper ivory ground |
| `--card` | `#fffdf6` | scoresheet surfaces |
| `--ink` | `#211b15` | warm near-black text |
| `--seal` | `#c8402a` | the red pen: CTAs, verdicts, active states, the seal stamp — nothing else |
| `--indigo` | `#274060` | the Evaluator's voice: evidence meters, interviewer rule, links |
| `--gold` | `#b3901f` | in-progress / partial states |

Restraint rule (Linear-style): exactly one chromatic accent for interactive elements; structure is
1px hairlines, not shadows; no gradients, no purple.

## Type — every face glyph-verified for full Vietnamese (đ, ơ/ư, stacked diacritics)

- **Phudu Variable** — display. A revival of hand-painted Vietnamese billboard lettering by
  Dương Trần; the single most on-brand headline face possible for this product.
- **Be Vietnam Pro** — UI/body; designed for Vietnamese text.
- **JetBrains Mono Variable** — every number, score, skill id, tag, and metadata strip (the
  "engineered scoresheet" register).

VN-safe metrics are load-bearing: display line-height ≥ 1.15, body ≥ 1.55, no `overflow: hidden`
on text containers — stacked marks (ỗ, ậ) clip under the trendy 0.9–1.0 leading. QA strings:
"Nguyễn Thị Thùy Dương", "PHỎNG VẤN THỬ", "ỗ ậ ữ ề ị".

Hard bans (fonts whose files lack Vietnamese despite metadata claims): Clash Display, General
Sans, Satoshi, Cabinet Grotesk, DM Sans, Poppins, Sora, Fira Code.

## Signature element

The grading seal (`web/src/components/Seal.tsx`): a double-ring red stamp — ring text
"LUYỆN PHỎNG VẤN · INTERVIEW COACH", center "PV" — stamped (rotated −7°, `stamp-in` scale
animation) as the brand mark, on the setup hero, and as the report's readiness verdict. Spend the
boldness in one place; everything around it stays quiet.

## Voice by structure

- Transcript = magazine interview: a mono speaker rail + a 68ch reading column; the interviewer
  speaks behind an indigo rule, the candidate in plain ink — no chat bubbles.
- Evidence meters are always indigo (the Evaluator never grades in red; only verdicts are red).
- Numbering (phase tabs 01–03, topic ledger, day cards) is honest sequence, not decoration.
- Grain: one `feTurbulence` pass at 5% over the paper — texture never over meaning.
- Motion: `rise-in` entrances, meter width transitions, the seal stamp; `prefers-reduced-motion`
  collapses all of it.
