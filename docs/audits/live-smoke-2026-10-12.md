# Live smoke — 2026-10-12 (#142)

- Commit: `830ddcf` (`main`), image built from it.
- Judge fingerprint, computed **inside the running image**:
  `sha256:03cabecb0ba6f517090b02b840432a92dc0194304aa2ca8540533d02f98a6975`. It is identical to
  `judge.lock`, so the judge that served this run is the judge the lock pins.
- Stack: `docker compose` (`app` + `nginx`), both `healthy`. TLS uses the 2026-09-15 dry-run's
  self-signed cert at `https://coach.localtest.me`. The state volume is the one left by that dry-run.
- Driver: a WebSocket client that does what the browser does. It sends the `auth` frame, then
  `start_session`, answers each `question` by its `turn_id`, waits for `session_completed`, and
  downloads `export.md` with the bearer token. The client is not a browser. It sends Origin
  `http://localhost:5173`, which is in `COACH_ALLOWED_ORIGINS`.
- **Keys: dev keys.** Both provider keys were pasted into a chat transcript before this run, so they
  fail pilot pre-flight line 1. #139 stays open; rotate them before anyone else uses the deployment.

## Results

| | Demo | Live |
|---|---|---|
| status / stop reason | `complete` / `max_questions` | `complete` / `max_questions` |
| questions / answered turns | 2 / 2 | 2 / 5 |
| wall time | < 1 s | 49.6 s |
| export | HTTP 200, 9,215 bytes | HTTP 200, 23,429 bytes |
| tokens | 0 | **26,478** (21,044 prompt + 5,434 completion), cap was 100k |
| provider calls | 0 | 15, all `outcome=ok`, no retries or transport errors |

Live calls by role, read from the `llm-call` lines (#144):

| role | calls | prompt | completion | total | seconds |
|---|---:|---:|---:|---:|---:|
| diagnostic | 1 | 418 | 254 | 672 | 3.9 |
| interviewer | 6 | 5,885 | 588 | 6,473 | 10.2 |
| judge | 5 | 9,051 | 1,617 | 10,668 | 14.3 |
| planner | 2 | 4,730 | 2,891 | 7,621 | 19.0 |
| supervisor | 1 | 960 | 84 | 1,044 | 2.2 |

Per-call latency: p50 2.65 s, max 11.3 s (the planner's first draft).

## Checks

- **Accounting.** `coach usage` reports 15 calls and 26,478 tokens under the Session id. That
  matches the 15 `llm-call` lines exactly, so every call was counted once. The accounting line reads
  healthy, and the server log has no `ACCOUNTING`, `Traceback` or `ERROR` line.
- **Judge pin.** All 5 judge calls went to `openai` / `gpt-5.4-mini`. Five judge calls is one per
  answered turn: the Panel never escalated.
- **Trace attribution (#144) on live traffic.** Every line carries `session=`. Questions 1–2 and
  turns 1–4 are numbered. The interviewer makes 2 calls per follow-up (the `lookup_concept` turn,
  then the follow-up itself); the supervisor, diagnostic and planner carry their own role.
- **Re-ask guard (#132) on live traffic.** Question 2's three follow-ups were three different
  questions. The micro-loop stopped at the safety cap (4 turns) because the Evaluator kept asking.
- **Ledger path (#122).** Candidate `smoke-20261012` was persisted with `ml_fundamentals` and `mlops`
  through `update_posteriors`.

## Observations (not defects)

1. **The planner's first draft failed its own validator.** The error was "schedule may include at
   most 2 resource-free review days; got days [4, 12, 13, 14]". The structured-output repair fixed it
   on the next call, at a cost of one extra call and ~4.5k tokens (17% of this Session). If it recurs,
   the rule belongs in the planner prompt rather than only in the validator. Watch it; do not file it
   yet.
2. **Question 1 scored 1.00 because of the smoke client, not the judge.** The client's keyword
   router answered a cross-entropy question with its data-leakage answer (the word "cross" matched).
   Scoring an off-topic answer 1/5 is the correct behaviour.
3. **One two-question Session cost ~26.5k tokens.** That agrees with the ~27k "measured Session"
   figure that `coach usage` uses to size its per-run budget.

## Not covered by this run

- A person in a real browser. CI's Playwright specs cover the browser path, in demo mode.
- `vn` and `mixed` language modes live, and a live Panel escalation (none triggered).
- Pre-flight lines 2, 3 and 11: production origin, production token, a real certificate.
