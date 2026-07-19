# Frontend redesign — Rice Paper & Red Ink brand system

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#60](https://github.com/nekloyh/get-hired/issues/60) (R-05) · implementation already open as [PR #50](https://github.com/nekloyh/get-hired/pull/50)

## What to build

PR #50 is a ground-up visual redesign ("Giấy Dó & Mực Đỏ" — rice-paper ivory ground, one chromatic
voice, the lacquer-red grading seal) that arrived implementation-first: there was no slice doc and
no acceptance criteria, which violates the project's own convention that content and features enter
through a spec. This doc retro-fits the contract so the PR can be reviewed against something, and so
the redesign never blocks main health again (its one build fix was extracted to main by R-02/#57).

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
- Lands in Wave 2/3. It must never gate Wave 0/1 fixes.

## Acceptance criteria

- [ ] Vietnamese glyph QA: a fixture string with stacked diacritics (e.g. "Kiểm định giả thuyết —
      phường Đống Đa, huyện Krông Pắc; ề ể ễ ệ ỡ ợ ữ ự — Kỹ sư học máy") renders in all three faces
      with no fallback-font tofu, checked at display and body sizes.
- [ ] No internal-jargon copy on user surfaces: rg over `web/src` finds no "Micro-loop",
      "Supervisor", "Beta prior", or raw enum strings rendered to the Candidate.
- [ ] `cd web && npm run build` exit 0 (tsc + vite).
- [ ] `cd web && npm test` green (20/20 or current count).
- [ ] `npm run test:e2e` demo-flow spec green on chromium + mobile-chrome.
- [ ] CI (both jobs) green on the PR after rebase onto post-Wave-0 main.
- [ ] `prefers-reduced-motion` respected (grain/motion passes disabled) — spot-check via devtools
      emulation.

## Out of scope

- i18n of chrome strings (R-30/#85 — do not translate the old skin twice).
- Session-history dashboard (R-28/#83).
- Any change to WebSocket/session semantics.
