# Frontend redesign — Rice Paper & Red Ink brand system

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#60](https://github.com/nekloyh/get-hired/issues/60) (R-05) · first implementation: [PR #50](https://github.com/nekloyh/get-hired/pull/50), code kept at tag `archive/pr-50-frontend-redesign` (`a0c090d`)

## What to build

PR #50 was a ground-up visual redesign ("Giấy Dó & Mực Đỏ" — rice-paper ivory ground, one chromatic
voice, the lacquer-red grading seal) that arrived implementation-first: there was no slice doc and
no acceptance criteria, which violates the project's own convention that content and features enter
through a spec. This doc retro-fits the contract so any implementation, including work resumed from
that tag, can be reviewed against something, and so the redesign never blocks main health again (its
one build fix was extracted to main by R-02/#57).

The redesign's product intent, in the project's vocabulary:

- **Brand carries the pedagogy.** The grading-seal verdict, indigo Evaluator voice, and
  technical-scoresheet structure make the *judge* — the product's core differentiator — visible,
  instead of a generic chat skin.
- **Vietnamese-first typography.** Every face must render full Vietnamese including stacked
  diacritics (Phudu display, Be Vietnam Pro UI, JetBrains Mono numerics).

## Scope guard

- UI contract stays frozen: labels, placeholders, button names, aria-labels unchanged (the
  existing vitest + Playwright suites are the enforcement).
- No new user-facing features ride along — pure reskin. Feature work (session history, i18n
  chrome) is tracked separately (#83, #85).
- Its order is the GitHub milestone #60 sits in. It must never gate a fix to `main`.

## Acceptance criteria

- [ ] Vietnamese glyph QA: a fixture string with stacked diacritics (e.g. "Kiểm định giả thuyết —
      phường Đống Đa, huyện Krông Pắc; ề ể ễ ệ ỡ ợ ữ ự — Kỹ sư học máy") renders in all three faces
      with no fallback-font tofu, checked at display and body sizes.
- [ ] No internal-jargon copy on user surfaces: rg over `web/src` finds no "Micro-loop",
      "Supervisor", "Beta prior", or raw enum strings rendered to the Candidate.
- [ ] `cd web && npm run build` exit 0 (tsc + vite).
- [ ] `cd web && npm test` green (20/20 or current count).
- [ ] From `web/`, with `uv run coach api` running,
      `bash ../.github/e2e-ran.sh demo npx playwright test e2e/demo-flow.spec.ts --project=chromium`
      and the same with `--project=mobile-chrome` pass with zero skipped tests (a `test.skip` exits 0,
      so plain `npm run test:e2e` reports green when no backend answers).
- [ ] Every job in `.github/workflows/ci.yml` green on the PR after rebase onto `main`.
- [ ] `prefers-reduced-motion` respected (grain/motion passes disabled) — spot-check via devtools
      emulation.

## Out of scope

- i18n of chrome strings (R-30/#85 — do not translate the old skin twice).
- Session-history dashboard (R-28/#83).
- Any change to WebSocket/session semantics.
