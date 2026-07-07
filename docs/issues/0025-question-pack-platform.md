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

- [x] Pack spec documented; `coach pack lint` validates schema + cross-references and dies loudly
      with a named violation on a bad pack
- [x] `coach session --pack <dir>` runs entirely from the pack; the default bank keeps working
      unchanged as the reference pack
- [x] `target_difficulty` influences selection — test: same Topic Plan, different targets ⇒
      different questions chosen
- [x] A returning Candidate does not get the identical question sequence (rotation aware of
      session history; integrates with the ledger id when 0023 lands, but must not require it)
- [x] The FPT-style pack ships with ≥20 lint-clean questions including the EN self-intro item

## Blocked by

- ADR 0008 (the contract decision). Related: 0013 (its remaining breadth tail should be authored
  as pack content once the contract exists — do not close 0013 from here).

## Done

- `bank.py` loaders are parameterized over a YAML reader, so the same fail-loud cross-referential
  validation runs on the built-in bank and on an external directory. New `load_pack(dir) -> Pack`
  (questions + concepts + metadata) and `coach pack lint <dir>` (nested subcommand) die with a named
  `BankError` and non-zero exit on any violation.
- `coach session --pack <dir>` runs the whole Session from the pack: its questions become the
  `question_bank` threaded through `build_session_graph` (selection + the Supervisor's seed-availability
  rails), and its concept notes back the Interviewer's lookups. The built-in bank is unchanged as the
  reference pack.
- `SeedQuestion` gained a `difficulty` (1–5) field; `select_seed_question` ranks by closeness to the
  Topic Plan's `target_difficulty` so an easy vs hard target lands on different prompts. The built-in
  bank was tagged with a 2/3/4 spread per Skill.
- `rotation_offset(session_id, span)` (stable SHA-256 hash) rotates the bank per Session so a returning
  Candidate does not get the identical sequence — no ledger required.
- Ships `data/packs/fpt/` — an FPT-style pack: 20 lint-clean questions across the five canonical
  Skills (flavoured after public FPT interview reports) including an English self-introduction item,
  plus 10 concept notes. (Taxonomy note: FPT's OOP/SQL emphasis is mapped onto the canonical Skills;
  genuinely new Skills would need a taxonomy change, out of scope here.)
- Pack spec documented in the README ("Content packs").

## Verified

- `uv run pytest tests/test_pack.py -q` — 10 passed: FPT pack loads + covers every canonical Skill;
  fail-loud on missing dir / dangling concept / missing Skill / bad difficulty / missing name;
  `target_difficulty` picks different questions; rotation varies across Session ids; a full offline
  Session runs entirely from the pack (asked prompts ⊆ pack, disjoint from the built-in bank); and the
  `coach pack lint` CLI returns 0 on a good pack and 1 on a bad one.
- `uv run coach pack lint data/packs/fpt` — "20 question(s) across 5 Skill(s) and 10 concept note(s)."
- `uv run pytest -q` — 199 passed, `ruff check` clean (built-in bank behavior unchanged).

## Status

**Closed.** Acceptance criteria are implemented and covered.
