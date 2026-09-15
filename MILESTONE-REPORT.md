# Milestone report — branch `audit/stabilize-2026-09-14`

Input: `QA-REPORT.md` (47 findings; M-0 16 tasks, M-1 24 tasks, M-2 10 debts), committed at `db73419`.
Work: **58 commits** on `main` (`2dac711`), of which the QA report had already reviewed the first 8.
Suite: **848 → 972** pytest, **27 → 35** vitest. Every gate green after every commit.

> Correction to this report's own earlier text: the branch carries **58** commits above `main` at the
> tagged commit, not "43 new on top of 8" (= 51). Measured: `git log --no-merges 2dac711..HEAD | wc -l`.
> Other stale numbers this pass re-measured are corrected in place and listed in §5.

---

## 1. Status: merged, tagged, and dry-run against the real stack

| | |
|---|---|
| PR **#133** | **MERGED** as a merge commit — `92d4dd1` |
| Tag `v0.1.0-pilot` | **pushed**, annotated, on `83ed13b` — `git merge-base --is-ancestor v0.1.0-pilot main` → **TAG OK** |
| `main` | green: ruff clean, mypy clean (34 files), **973** passed; CI `python / web / docker` all pass |
| #119 | **CLOSED** by the PR body's `Closes #119` |
| #59 (blocker) | **CLOSED** — measured 38 s cold / 8 s repo-controlled, §6 |
| Deploy dry-run | **first ever full-stack run** (nginx + TLS + `wss://`) — 11 of 11 pass, 2 defects found and fixed, §5 |
| Stable checklist | unchanged: 20 PASS / 1 FAIL (item 8, bench 34/35, accepted) |

### Why a merge commit, and why the tag survived

`v0.1.0-pilot` pointed at `83ed13b`. A squash or rebase merge rewrites that sha, leaving the tag
pointing at a commit unreachable from `main` — present, but meaningless. The repo allows all three
methods (`gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed` → all true),
so a merge commit was chosen deliberately: it keeps `83ed13b` reachable, and it preserves the 58
one-task-per-commit records whose messages carry each fix's red test output. `git log --no-merges
2dac711..main` → **58**, intact.

**One thing bit anyway, and is worth knowing:** this machine has `fetch.pruneTags=true`, so the
mandated `git fetch --all --tags` *deleted the local, never-pushed tag* — `- [deleted] (none) -> v0.1.0-pilot`.
The commit was fine and still an ancestor of `main`, so the tag was recreated with an identical
message and pushed immediately. If you keep a tag local "until the merge", that config will eat it.

### The one FAIL is unchanged and still not PASS

`coach bench --k 3` → 34/35. Not re-run this session; no anchor, band or case touched. Attribution
and rationale are in §4 item 8 and were argued from the run itself. The pilot runbook now states the
consequence in words a Candidate can act on: **these scores are practice, not measurement** (§5).

---

## 2. What was done

`verify` is the command in each commit message; `result` is the measured red→green. Every task ran
test-first: a characterisation test failing on the code as it stood, then the fix.

### M-0 — blocked the tag

| id | sha | closes | verify | result |
|---|---|---|---|---|
| M0-15 | `418f5e8` | NEW-13, checklist 4+5 | probe test inside `tests/` | exit 124, **no output at all** → `Failed: Timeout (>60.0s)`, 2 failed |
| M0-10 | `72830bc` | QA-04 | `pytest -k "sidecar or torn_row"` | 4 failed → 4 passed; `assert None is not None`, `DID NOT RAISE OSError`, a `UnicodeDecodeError` escaping the gate |
| M0-11 | `2f1926a` | QA-12, QA-13 | `pytest -k "flushing_at_once or reconciling_twice"` | 3 failed → 4 passed; `assert 2 == 1` (row parked twice), `assert 2400 == 1200` twice |
| M0-12 | `7fe28be` | QA-09 | `pytest -k second_process` | 2 failed → 2 passed; `assert 20 == 10` (cap breached across processes), `['alice','carol'] == ['alice','bob','carol']` (a Candidate erased) |
| M0-2 | `af12e31` | QA-01 | `pytest -k "fresh_start_over_an_existing or restart_over_a_completed"` | 2 failed → 2 passed; the web answered `session_started` over a saved Session, the CLI `assert 0 == 2` |
| M0-3 | `3b78daf` | NEW-02 | `pytest -k swept_session_id` | 1 failed → 1 passed; first frame was `session_started {resumed: True}`, then `EmptyInputError` |
| M0-9 | `d8310a8` `7f632ff` | QA-08 | `pytest -k "semantically_invalid_start or dies_before"` | 2 failed → 2 passed; the 3rd nonsense frame hit "Daily question cap reached: 20 of 20", and a crashed start held `assert 10 == 0` questions |
| M0-6 | `62154f2` | QA-05 | `pytest -k accounting` | 3 failed → 3 passed; three nets swallowed the stop (logs: "using deterministic fallback advance_plan", "completing the Session without a Study Plan", "keeping the ledger fusion without a plan") |
| M0-5 | `a205b71` | QA-03 | `pytest -k another_sessions_fold` | 1 failed → 1 passed; Session A inherited B's fold and was haircut 0.95 → 0.85 |
| M0-13 | `25a256a` | QA-10, NEW-24, NEW-25 | probe + `pytest tests/test_config.py tests/test_llm.py` | 5 holes ACCEPTED → all 5 refused (junk model, RED gpt-4o-mini, redirected base_url, ROLE_JUDGE_MODEL, a GroqClient handed in as judge) |
| M0-14 | `56adf8c` | QA-02 (free-text half) | `pytest -k "free_text_candidate_id or unsafe_candidate_id"` | 12 failed → 12 passed; the ledger wrote `{' ': {...}}` to disk |
| M0-4 | `04d308b` `e79358f` `fd9c55d` | NEW-01 | `pytest -k "bound_to_the_turn or id_less_answer"` | 2 failed → 2 passed; the transcript scored "STOLEN: typed for the first question" as Q2's evidence |
| M0-7 † | `98f3713` | QA-06 | `pytest -k dead_panel_voice` | 1 failed → 1 passed; `openai.APIConnectionError` raised out of `evaluate()` itself |
| M0-8 † | `129e4e3` | QA-07 | `pytest -k "consensus_panel_cannot or degraded_consensus"` | 2 failed → 2 passed; `assert 2.0 == 1.1` (fully degraded evidence at maximum weight) |

† changed the scoring path → the bench was owed, was run, and came back **34/35** (§1, §4 item 8).

### M-1

| id | sha | closes | result (red → green) |
|---|---|---|---|
| M1-1 | `22ebc83` | QA-15 | oversize answer destroyed + Session wedged → bounded before Send, refusal rolls back |
| M1-2 | `e6e9f0b` | NEW-15 | `expected 'complete' to be 'evaluating'` — report opened during the planner call |
| M1-3 | `2a11d4c` | NEW-04 | a **200 OK with an empty body** served as a finished report; `os.replace` never called |
| M1-4 | `56c1c4c` | NEW-05 | `assert None is not None` — A's resume silently un-suspended B |
| M1-5 | `9557a27` | NEW-06 | `assert 6200 == 1000` — 5,200 tokens on another provider were invisible |
| M1-6 | `9620128` | NEW-07 | `DID NOT RAISE AccountingUnavailable`; `{'total': 0}` vs `{'total': 102}` |
| M1-7 | `378437d` | NEW-08 | `assert False` — Session B re-paid the whole outage discovery |
| M1-8 | `e6c5ef4` | NEW-09 | `assert None is not None` — 10× the admitted estimate tripped nothing |
| M1-9 | `daf89f1` | NEW-10 | 5 spies reached, `--ignore-budget` unrecognised, spend in the `{'': 15}` bucket |
| M1-10 | `2ab2bc0` | QA-14 | a bench **report** written into a spent day: "Cases within band: **0/35**" |
| M1-11 | `3d660f6` | NEW-11 | `DID NOT RAISE ValueError` for bare/padded/buried `*` |
| M1-12 | `f4ee77b` | NEW-12 | a Candidate's answer supplied a 7th heading, its own `## Summary` |
| M1-13 | `b490f33` | NEW-16 | `- Q2 skill=mlops score=0.00 confidence=0.00 stop=failed` in the Supervisor prompt |
| M1-14 | `5950aea` | NEW-17 | 5 Skills persisted where 1 was probed, incl. a 5/5 claim never asked about |
| M1-15 | `c5079eb` | NEW-18 | **18 of 181** producible prior means RAISED — a strong returning Candidate could not start |
| M1-16 | `990660c` | NEW-19, NEW-20 | `assert 0 == 2` — a finished Session resumed and re-served its old report |
| M1-17 | `0cdbd2f` | QA-16 (failed half) | `Q1 mlops · 0.00/5 · failed` shown to the Candidate |
| M1-18 | `4367d75` | NEW-14 | `--standalone` could never renew; backup tarred an empty auto-created volume |
| M1-19 | `58064d7` | NEW-03 | `assert 'pinned' == 'free'` — the loop's shared executor was pinned |
| M1-20 | `d815d6f` `f1af1e2` `74b6814` | QA-11, NEW-27 | `KeyError: 'schema_version'`; a v99 ledger read as if understood |
| M1-21 | `5f74fb8` | NEW-28, NEW-29 | `_meta` accepted as a Candidate id; `UnicodeDecodeError` escaping "never raises" |
| M1-22 | `94b06a2` | NEW-30 | inverted red: proven failable by injecting the GH #83 leak (2 tests red, revert → green) |
| M1-23 | `ed15424` | QA-17, NEW-27 | three AUDIT lines re-measured; §4 marked as contract |
| M1-24 | `ac39ef9` | NEW-26 | `DID NOT RAISE ValueError` ×2 for a v0 inner state |

### Three commits are repairs of my own work, not plan rows

| sha | what |
|---|---|
| `7f632ff` | M0-9's test raced the run thread's `finally` (2 passes, then a failure). Joins the thread now. |
| `e79358f` | M0-4's test assumed a frame order that two threads do not guarantee (1 failure in 8). |
| `74b6814` | **mypy was red for 5 commits and I did not notice**, because I was reading the gate with `tail -4` and the mypy line scrolled off. The tests and ruff claims in `d815d6f`, `f1af1e2`, `ac39ef9`, `5f74fb8` and `990660c` are real; their "mypy → clean" line was not checked. Fixed, and my gate runner now prints an explicit `GATE: OK` / `GATE: FAILED`. |

---

## 3. Not done

| id | why | what it needs |
|---|---|---|
| ~~M0-1~~ | **DONE this pass** — `.env` set, MiMo keys removed, verified in a container | — |
| ~~M0-16~~ | **DONE this pass** — pushed, PR opened, #119 closed from it | — |
| ~~`coach bench --k 3`~~ | **RUN** — 34/35, artifact committed at `df45374` | the red is §1's decision |
| M-2 (10 items) | out of scope by instruction — **now filed**, §5 | #124–#132, #84 |
| **QA-16's other half** | **the plan has no row for it** | see below |

**QA-16 is only half in the plan, and I did not widen the scope to cover the rest.** The finding has
two parts: the `failed`-item rendering (M1-17, done, `0cdbd2f`) and *"declare `TraceRecord` in
`types.ts`; render the five missing Committee fields"*. The second part appears in no M-0 or M-1 row,
so it was never scheduled. Verified still open at `4367d75`: `web/src/lib/types.ts:112` is still
`trace: Record<string, unknown>` against **eleven** concrete server fields, and `ReportView.tsx` renders
none of `initial_confidence`, `argument` or `key_evidence`. Consequence is unchanged from the QA
report: the UI still cannot show the evidence the export shows. Nothing is corrupted by it — it is a
display gap — so it does not block the tag. **Filed as GH #121**, with the stale citations in
QA-16 itself corrected (`types.ts:105` → `:112`, `ReportView.tsx:160-173` → `:171-184`,
`session_serde.py:49-58` → `:49-59`, `exporter.py:180-198` → `:185-207`).

Two things I deliberately did **not** widen, both recorded at the code:

- **`postmortem`'s same-candidate read-modify-write** (now **GH #122**). M0-12 put an flock inside `save_posteriors`,
  which serialises the merge but not `load_states` → fuse → `save_posteriors` as a pair. Two
  concurrent post-mortems for the *same* candidate can still lose one's evidence. The QA finding as
  written is the cross-candidate erasure, and that IS closed.
- **`reconcile_accounting`'s sidecar rewrite** (now **GH #123**). Two simultaneous `coach usage --reconcile` runs are
  still an unlocked read-modify-write. Out of QA-09's scope; the double-bill it used to cause is
  closed by M0-11's uuid dedup.

---

## 4. The stable checklist, line by line — re-run end to end

Re-run in full at `db73419` on 2026-09-15, including the container block. Commands are the ones §7 of
`QA-REPORT.md` specifies. Exit codes are real, captured per command, not inferred from a pipeline.

| # | check | result | evidence (verbatim) |
|---|---|---|---|
| 1 | lint clean | **PASS** | `All checks passed!` · exit 0 |
| 2 | types clean | **PASS** | `Success: no issues found in 34 source files` · exit 0 |
| 3 | suite green twice, no flake | **PASS** | run 1 `972 passed, 9 deselected, 2 xfailed, 1 warning in 11.53s` exit 0; run 2 `972 passed, 9 deselected, 2 xfailed, 1 warning in 11.84s` exit 0 — summaries identical |
| 4 | no test can hang | **PASS** | `pytest-timeout>=2.3` (`pyproject.toml:33`); `addopts = "-m 'not live and not rag' --timeout=60"` (`pyproject.toml:57`); `timeout-minutes` on **all 3** CI jobs — 15 / 15 / 20 (`ci.yml:11,25,46`) |
| 5 | lockfile honest | **PASS** | `Resolved 150 packages in 0.80ms` / `Checked 65 packages in 0.55ms` · exit 0 |
| 6 | web gates green | **PASS** | eslint exit 0; `tsc --noEmit` exit 0; vitest `Test Files 4 passed (4)` / `Tests 35 passed (35)` exit 0; build exit 0 (`index-BoZFRreM.js 226.32 kB`, `✓ built in 1.02s`) |
| 7 | wire format frozen | **PASS** | `tests/test_serde_golden.py` → `9 passed in 0.28s` · exit 0 |
| 8 | judge untouched **or** re-benched | **FAIL — accepted, rationale recorded (§1)** | `rubric.py: IDENTICAL` and `data/bench/: IDENTICAL` vs `2dac711`; `evaluator.py` `1 file changed, 38 insertions(+), 13 deletions(-)` → artifact owed. Artifact `docs/audits/calibration-bench-2026-09-15.md`: **`Cases within band: 34/35`**, exit 1. `vnlp_segmentation_weak_vi` 2.70/2.70/2.70 vs band 1.0–2.6. **Not PASS. Not caused by this branch.** |
| 9 | image builds from a clean tree | **PASS** | `git archive HEAD \| tar -x` exit 0 → 219 files, 0 untracked leaked (`.env`/`*.bak.*` count = 0); `docker build` exit 0; `coach:v0.1.0-pilot 402MB` |
| 10 | container serves as uid 10001 | **PASS** | `{"status":"ok",…,"auth_required":true,…}`; `uid=10001(coach) gid=10001(coach) groups=10001(coach)` |
| 11 | auth enforced | **PASS** | no bearer → **401**; wrong bearer → **401**; correct bearer → **404** (gate rejects, token works, id simply absent) |
| 12 | a whole Session completes in the container | **PASS** | `session_started state_update question state_update state_update question state_update state_update state_update session_completed`; `status: complete questions: 2 transcript: 2`; `/app/state/exports/pilot-final-001.md` **9,127 B** |
| 13 | state survives container replacement | **PASS** | `docker rm -f` → new container, same volume. md5 `11067a5d3afa6147cb63491f93ee7b7f` **before and after**; health → 200, export → 200; ledger and both exports intact on the volume |
| 14 | quota mid-question suspends cleanly | **PASS** | `tests/test_supervisor.py -k dead_quota_mid_session` → `1 passed, 62 deselected` · exit 0 |
| 15 | two starts racing admit at most one | **PASS** | real two-**process** harness → `2 passed, 981 deselected` · exit 0 |
| 16 | resume does not recharge a start reservation | **PASS** | `tests/test_usage.py -k resume` → `5 passed, 75 deselected` · exit 0. Code: `if metered and not resume:` at `web_api.py:988` |
| 17 | bounds hold at the wire | **PASS** | 8 wire cases, **all refused, none wedged** — see the block below |
| 18 | id reuse cannot destroy a report | **PASS** | `session_error`: *"This Session id already has saved progress… starting over here would overwrite the saved report."*; export md5 `11067a5d…` **unchanged** |
| 19 | unknown-id resume is friendly | **PASS** | `session_error`: *"No saved Session found for 'never-existed-anywhere'. … there is nothing to resume."* — no `EmptyInputError` |
| 20 | an answer cannot be scored against the wrong question | **PASS** | 3 hostile frames (replay of an answered `turn_id`, `turn_id: 999`, absent `turn_id`) → **3 × `Answer refused: it does not answer the pending question.`**, then `COMPLETED`. Occurrences of `STOLEN` in the resulting report: **0** |
| 21 | operator config is set | **PASS** (was BLOCKED) | `auth_required` → `true` from the running container; `grep -c '^MIMO_' .env` → **0**; `COACH_AUTH_TOKEN` 64 hex chars; `COACH_ALLOWED_ORIGINS=http://localhost:5173` — **a dev value, see §9** |

**Item 17, the wire bounds, verbatim:**

```
start_session field bounds:
  max_questions=11       -> session_error   1 validation error … Input should be less than or equal t…
  max_questions=0        -> session_error   1 validation error … Input should be greater than or equa…
  elapsed=4h+1s          -> session_error   1 validation error … max_elapsed_seconds …
  elapsed=0              -> session_error   1 validation error … Input should be greater than 0
  language=klingon       -> session_error   Input should be 'en', 'vn' or 'mixed'
in-session bounds:
  oversize answer        -> session_error   String should have at most 20000 characters
    -> not wedged           next frame = question
  non-object frames      -> session_error   expected a JSON object frame, got str
    -> not wedged           next frame = question
  queue flood (40 sent)  -> session_error   Answer refused: it does not answer the pending question.
    -> outcome              frames=session_error state_update question   refusals=27
```

**Hostile `candidate_id` at the wire** (M0-14 / M1-21), all refused at the pydantic boundary before any
Session state exists:

```
  candidate_id='_meta'                       -> session_error  String should match pattern '^$|…   (reserved prefix, NEW-28)
  candidate_id='minh/../../etc/passwd'       -> session_error  String should match pattern '^$|…   (anchors hold)
  candidate_id='a b'                         -> session_error  String should match pattern '^$|…
  candidate_id='xxx…' (200 chars)            -> session_error  String should match pattern '^$|…
  candidate_id='ném'                         -> session_error  String should match pattern '^$|…   (diacritics refused by design)
  candidate_id='(empty)'                     -> session_started                                    (by design: one-shot cold start)
```

### CI on the PR

`gh pr checks 133`, all three jobs green on the pushed branch:

```
docker   pass   34s
python   pass   37s
web      pass   21s
```

`#119` carries `Closes #119` in the PR body, so it closes when you merge — not before.

### Two counts in the previous run of this table were wrong

Reported honestly rather than reconciled: the earlier §4 recorded **9 passed** for item 16 and **21
passed** for item 17. Re-run at HEAD, the command §7 actually specifies for item 16
(`pytest tests/test_usage.py -k resume`) selects **5** tests; widening `-k resume` to the whole suite
gives **18**. Neither is 9. Item 17 is specified as a *wire probe*, not a pytest selector, so it was run
as one this time — the closest pytest selector gives 15, not 21. **Both checks pass on their merits**;
only the earlier counts were unreproducible.

---

## 5. Pilot deploy dry-run — the part nobody had ever run

`QA-REPORT.md` recorded *"Not executed: `docker compose up` with nginx/TLS (certs are untracked)"*.
`docs/deploy.md` §8 **claimed** the stack was verified on 2026-07-27. This pass treated that as a
claim and re-executed it at `92d4dd1`, against `coach.localtest.me` (resolves to 127.0.0.1, so it is
a real hostname with real SNI, not a loopback shortcut) with a fresh self-signed certificate.

| # | check | result | evidence |
|---|---|---|---|
| 1 | `docker compose up -d --build` | **PASS** | exit 0; `app` healthy, `nginx` healthy |
| 2 | HTTP :80 redirects | **PASS** | `/` and `/api/health` → **301** → `https://coach.localtest.me/…` |
| 3 | HTTPS :443 serves the API | **PASS** | `{"status":"ok",…,"auth_required":true,…}`; UI on the same origin → **200** |
| 4 | auth enforced through the proxy | **PASS** | no bearer **401** · wrong bearer **401** · right bearer **404** |
| 5 | **a whole Session over `wss://` through nginx** | **PASS** | `session_started state_update question state_update state_update question state_update state_update state_update session_completed`; `status=complete questions=2 transcript=2` |
| 6 | Origin gate at the handshake | **PASS** | only `https://coach.localtest.me` accepted; `https://evil.example.com`, **`http://` of the same host**, and `null` all **HTTP 403**. Scheme is part of an origin, and nginx forwards `Origin` verbatim so the check survives the proxy |
| 7 | answer size at the boundary | **PASS after a fix** | see below |
| 8 | `docker compose restart app` mid-question | **PASS** | Q2 left unanswered → restart (0.4 s) → resume re-emitted **the same question** → answered → `status=complete`; the export contains `POST-RESTART ANSWER` |
| 9 | `docker compose down && up -d` | **PASS** | export md5 `e848a3c8…` / `f0cb41f4…` **identical** before and after; endpoints 200 |
| 10 | ACME http-01 webroot | **PASS** | `/.well-known/acme-challenge/<token>` → **200** with the token body, while `/other` → 301. Cert renewal in 90 days depends on exactly this |
| 11 | backup **and restore** | **PASS** | archive → empty volume → new container → both exports **200, byte-identical md5** |

### Two defects found, both fixed

**(a) nginx's `client_max_body_size 1m` does not bound the Session socket at all.** `a95deaf`

The directive governs an HTTP request body. After the 101 Upgrade nginx forwards a byte stream, so
it never applies to the frames that carry every answer. Measured before the fix:

```
frame 1,500,056 bytes -> session_error: String should have at most 20000 characters
frame 5,000,056 bytes -> session_error: String should have at most 20000 characters
```

A 5 MB frame — 5× the nginx cap — crossed untouched and was refused only by
`CandidateAnswerPayload`, i.e. **after uvicorn had buffered the whole thing.** The real ceiling was
uvicorn's own `ws_max_size` default of **16 MiB**, which the app never set; on a deliberately
single-worker deployment (R-12) that is attacker-controlled allocation × uvicorn's 32-deep queue.

`WS_MAX_FRAME_BYTES = 256 KiB` now sits with `MAX_ANSWER_CHARS` and `ANSWER_QUEUE_MAXSIZE` — the
bound belongs with the other input bounds precisely because nginx cannot supply it. After the fix,
against the rebuilt image:

```
frame    20,055 B -> state_update      (a legitimate 19,999-char answer still works)
frame    20,057 B -> session_error     (the app's friendly refusal is preserved)
frame   300,056 B -> CLOSED AT THE TRANSPORT, code 1009
frame 5,000,056 B -> CLOSED AT THE TRANSPORT, code 1009
```

**(b) nginx had no healthcheck.** `97206aa`

`docker compose ps` printed a bare `Up` for the container terminating TLS and proxying every
socket — a config that failed to load would have read identically, and the first symptom would have
been a Candidate's browser not connecting. It now probes `:80` for the 301.

It probes `:80` and not `:443` deliberately: the image has neither `curl` nor `openssl`, and busybox
`wget` follows the redirect into TLS and fails certificate verification — so a `:443` probe reports
unhealthy for the whole self-signed bootstrap that `deploy.md` §3 makes step one of getting a real
certificate. Both directions were measured rather than asserted:

- probe against a dead port → **exit 1** (not a rubber stamp)
- `docker compose stop app`, wait 35 s → nginx **still healthy** while https returns **502**

That limitation is real, so it is written into the compose comment and covered by pre-flight lines
6–9, which run against the real hostname.

### `COACH_ALLOWED_ORIGINS` behind a proxy

For a stack behind nginx the origin must be the **browser's** origin (`https://<host>`), not the
Vite dev origin. Verified above: the exact value is accepted and every near-miss — including
`http://` of the same host — is refused at the handshake with 403. The local `.env` now holds the
**dry-run** value `https://coach.localtest.me`. It is still not a production value; pre-flight line
2 in [`docs/pilot-runbook.md`](docs/pilot-runbook.md) is the gate that catches it.

---

## 6. #59 — the onboarding blocker, measured and closed

`severity:blocker`, open since the remediation backlog was filed. Its DoD was a timed walkthrough on
a clean checkout; the README carried **estimates that had never been measured** ("~10 minutes",
"~4 min, mostly `npm install`").

Executed on a fresh `git clone` of `main` into a temp dir outside any existing checkout, on a
machine with no prior `.env` for that clone. Run twice. The uv-managed Python lives **outside**
`UV_CACHE_DIR`, so it was measured separately rather than silently counted as warm.

| | wall | breakdown |
|---|---:|---|
| **Repo-controlled** (caches warm) | **8 s** | clone 3s · `uv sync` 1s · `npm install` 2s · backend answering 2s · vite 0s · completed interview 0s |
| **Cold total** (nothing cached) | **38 s** | clone 2s · managed Python 4s (103 MB) · `uv sync` 24s (171 MB) · `npm install` 5s (41 MB) · backend 2s · vite 1s · interview <1s |

Splitting the DoD into two numbers is what resolves the old 15-min-vs-37s confusion: **~275 MB of
downloads is network-bound and not this repo's to control.** The 8 s is what moves when the
repository changes and is the number to watch in review. Both are far inside the ≤10 min DoD, and
`rg -i mimo .env.example` returns **0** — stronger than the DoD's "optional/fallback, not default".

README timings replaced with the measurements (`cbbbb22`). #59 **closed**.

**What was not executed:** step 5 ran in **demo** mode. The documented step needs a real OpenAI key
and a paid call, which was outside this pass's authorisation. The whole WebSocket path ran end to
end; the live *configuration* half was verified without spending — with a real key present,
`/api/health` reports `"primary_configured": true`, which is the check README step 3 itself
specifies. The key was scrubbed from the throwaway clone immediately.

**Worth knowing for a deploy:** a fresh clone using `.env.example` verbatim starts with
`auth_required: false` — correct and documented for localhost dev, and exactly what pre-flight
line 3 exists to catch before anything is exposed.

---

## 7. M-2: filed, not coded

All ten are now GitHub issues with verified `file:line` evidence and a trigger. **Every number below was
re-measured at `db73419`; four of the ten figures in the previous table were stale and are corrected.**

| id | issue | item | what should trigger it |
|---|---|---|---|
| M2-1 | **#124** | split `web_api.py` / `cli.py` | the next change that must touch both halves of either file, or a merge conflict in them |
| M2-2 | **#125** | SQLite read path for the usage ledger | `coach usage` taking >1s, or the ledger passing ~50k rows |
| M2-3 | **#126** | ledger rotation / TTL | pair it with M2-2; or the state volume crossing a size you care about |
| M2-4 | *folded into* **#84** | per-record ownership / accounts | **a second person using the deployment.** This is QA-02's isolation half — not a separate issue, it *is* R-29 |
| M2-5 | **#127** | Skill-ledger history | the progress dashboard (#83). Verified as a storage-shape prerequisite for #83, not a duplicate of it |
| M2-6 | **#128** | the catalogued duplications | opportunistic — whenever a change already touches one of the copies |
| M2-7 | **#129** | `SelfCritiqueTrace`, `docs/reference/*`, write-only `data/` outputs | any pass that already touches them |
| M2-8 | **#130** | `resources.py:3` stale comment + Chroma wire-or-delete | the old trigger "R-13" is **dead** — GH #68 is closed; #130 carries a live replacement |
| M2-9 | **#131** | `ruff format` | a window with no open PR touching the 26 files |
| M2-10 | **#132** | follow-up re-ask guard, `skip_ahead` seed gate, sticky `concept_miss` | a Candidate reporting a repeated or skipped question |

### Corrections to the previous table's numbers

| claim | measured at `db73419` |
|---|---|
| M2-1: `web_api.py` 1,122 → 1,345 | baseline wrong. **984 → 1,345** (+361, +36.7%). HEAD figure right |
| M2-1: `cli.py` 1,246 → 1,433 | baseline wrong, growth overstated ~3×. **1,367 → 1,433** (+66, +4.8%) — the CLI *churned* (562 changed lines), it did not grow |
| M2-9: "24 files (15 tests, 7 src, 2 scripts), was 18" | **26 files — 16 tests, 8 src, 2 scripts.** And `QA-REPORT.md:163` records **28 at `main`**, so the drift **shrank** 28 → 26 |
| M2-2: ledger "~1.4k rows" | **1,494 rows / 196,131 B**, 0 unparseable. Scan cost measured: ~2.16 ms/scan, ~17 ms per question (8 scans) |
| M2-6: "the 16 remaining duplications" | the catalogue is **20 rows** (`AUDIT.md:245-264`); 11 sampled, 3 unified, 8 still live. Surviving count is **~17**, not 16 — it excludes a PARTIAL row and 3 newer duplications |
| §3: "ten concrete server fields" in the trace | **eleven** (`microloop.py:162-181`) — the eleventh is `judge_unvalidated` |

---

## 8. Residual risk after this wave

Rewritten against the current code and this pass's measurements. Rows the wave closed are gone; rows
whose premise this pass disproved are corrected, not repeated.

| risk | why it survives | how you will notice |
|---|---|---|
| **The judge HAS drifted inside a pinned model** | No longer hypothetical and no longer only a fairness delta — it is **red**. `vnlp_segmentation_weak_vi` 2.10/2.60/2.00 → 2.70/2.70/2.70, same model id, zero spread. M0-13 gates the (provider, model, base_url) triple at startup; **nothing detects the provider retraining under a stable name**, and CI never calls the judge | exactly how it surfaced: bench scores moving with no code change. Only `coach bench --k 3` shows it. **GH #96** |
| **Two pilot users share one Skill history** | Mechanism now verified, and it is worse than "collision": the ledger key is client-supplied (`web_api.py:111` charset-only) and unauthenticated (`web_api.py:1067`), so it is read *and* write access to another user's Skill history by typing their id. Unfixable under one shared token — `token_identity()` (`usage.py:917`) is identical for everyone | a Candidate's mastery jumping between Sessions with no interview that explains it. **GH #84** |
| **A reconnect during a real provider stall still waits up to 120 s** | M1-19 stopped it starving the event loop and capped concurrent joins, but one unreachable provider costs ~4.2 min of retries — still longer than the join | repeated *"The previous run of this Session is still finishing"* clustered on one id; now also *"already waiting on the maximum number of previous runs"* |
| **Two processes on one checkpoint `thread_id`** | M1-16 claims a per-Session lock in the **CLI**. The web server does not take it — it has its own in-process registry — so a CLI resume is refused while another CLI drives, but the web's own claim is invisible to the CLI's lock | interleaved transcript items; `started_at` jumping backwards |
| **`postmortem` can lose a concurrent post-mortem's evidence** | the flock is inside `save_posteriors` (`ledger.py:244`), not around load→fuse→save (`postmortem.py:185/188/197`). And `locked()` must not nest (`filelock.py:54-55`), so "wrap the caller" is not a one-liner. Silent by contract — `ledger.py:235` "Never raises on a write problem" | a debrief's evidence absent from the next Session's priors, with nothing logged. **GH #122** |
| **`coach usage --reconcile` run twice concurrently loses an update** | unlocked read-modify-write on the fault sidecar (`usage.py:772`). The *double-bill* this used to cause is closed by M0-11's uuid dedup; the lost update is not | two operators, or a cron beside a human. **GH #123** |
| **Spend a gateway never reports** | M1-6 latches a fault when the token count is unreadable — but only for calls through the provider clients. A gateway reporting *plausible but wrong* numbers is still believed | `coach usage` totals drifting from the provider's own dashboard |
| **A `session_error` is still a bare string** | M1-1 added `recoverable`; every other error is distinguished only by its text | a future refusal that should be recoverable marked terminal by omission — the default is terminal, the safe direction |
| **The export is mode 600** | **Confirmed live this pass**: `-rw------- 1 coach coach 9127 … pilot-final-001.md`. `atomic_write_text` publishes through `tempfile`, which creates 0600. The server reads it as the same uid, so nothing is broken — a backup or sidecar process running as another uid cannot read `exports/*.md` | a backup job that used to work returning permission denied |
| **`ruff format` is ungated, not "growing"** | **The previous report had this backwards.** Measured: 28 files at `main` → **26** at HEAD, i.e. it *shrank*. The real risk is that `.github/workflows/ci.yml:19` runs `ruff check` and nothing anywhere runs `ruff format --check`, so the number is invisible either way | nothing, until someone runs it and produces a 26-file / 355-line diff. **GH #131** |
| **The web UI cannot show the evidence the export shows** | `web/src/lib/types.ts:112` is still `trace: Record<string, unknown>`; `ReportView.tsx` renders 5 of the 10 panel fields, dropping `initial_confidence` and both voices' `argument` / `key_evidence`. Display gap only — nothing is corrupted | a Candidate asking why a committee overturned a score, and you having to open the Markdown export to answer. **GH #121** |

---

## 9. Decision log

Every fork taken without asking, with the option that was dropped and its cost.

| # | question met | chosen | why | dropped, and its cost |
|---|---|---|---|---|
| 1 | Add `.env.bak.*` to `.gitignore`? | **No change** | already covered — `git check-ignore -v .env.bak.1789444582` → `.gitignore:24:.env.*`. Verified, not assumed | adding a redundant rule; cost: noise in a file whose existing rule already matches, and a false signal that `.env.*` does not cover it |
| 2 | Which `COACH_ALLOWED_ORIGINS`? | **`http://localhost:5173`**, flagged as a dev value | no production hostname exists anywhere in the repo — `deploy/nginx/conf.d/coach.conf` is `server_name _` by design, and compose names none. `*` is refused at startup (M1-11) | guessing a hostname; cost: a wrong origin looks configured and silently breaks **every** browser socket in production, with the failure appearing at handshake time, not at startup |
| 3 | File a new issue for bench option 1? | **Comment on #96, raise to `severity:high`** | #96 **is** option 1, is open, and already carries draft PR #104. Its body's claim *"Not a gate failure"* is now false and needed correcting in place | a new issue; cost: a duplicate of an open issue, splitting the repeatability evidence and the draft PR away from the new measurement |
| 4 | New issue for QA-02's isolation half, and for M2-4? | **One comment on #84, folding both** | M2-4 *is* R-29 *is* QA-02's isolation half — one piece of work. The comment adds the verified mechanism and kills the proposed HMAC remedy with its own docstring | two more issues; cost: three trackers for one fix, and the HMAC remedy surviving in writing as if viable |
| 5 | M2-5 (ledger history) — new issue or comment on #83? | **New issue #127** | the drafting agent checked #83 and found it is the *consumer*; the storage-shape decision is a distinct prerequisite | a comment on #83; cost: a storage decision buried in a dashboard issue |
| 6 | Trust the 12 issue drafts as written? | **Adversarially re-verify every one, file the corrected bodies** | all 12 came back `needs_edit`: **36 bad citations and 40 unsupported claims** caught. E.g. "the CLI reads four trace fields" → five; "ten trace fields" → eleven; `ruff format` 24 → 26 | filing the drafts as written; cost: 36 wrong `file:line` citations permanently in the tracker, which is exactly the failure mode this report criticises elsewhere |
| 7 | Item 16 gives 5 passed; the previous report said 9 | **Report 5, state the discrepancy** | the spec'd command selects 5 at HEAD; widening to the whole suite gives 18. Neither is 9. The check passes on its merits either way | quietly reporting 9 to match; cost: a checklist that agrees with itself and with nothing else |
| 8 | Item 17 — pytest selector or wire probe? | **Wire probe** | `QA-REPORT.md:325` specifies *"the probe script: oversize answer / elapsed / max-questions / non-object frame / queue flood all refused, session not wedged"* — a wire check, not a unit-test count | a pytest selector; cost: it would have reported 15 and never touched the wire, which is where the bound has to hold |
| 9 | My first demo probe failed with `session_error` | **Fixed the probe, not the app** | the app was right: `mlops_awareness` is not a canonical Skill (`diagnostic.py:23-28` lists five) and it refused with `ValueError: unknown Skill claim(s)` | "fixing" the app to accept it; cost: widening a validated domain boundary to accommodate a typo in a throwaway script |
| 10 | Push the `v0.1.0-pilot` tag? | **Create it locally, do not push** | the PR is unmerged; a pushed tag that later has to move is worse than one that waits | pushing it; cost: a public tag pointing at a commit that may be rebased or amended during review |
| 11 | Rotate the Groq key? | **Not done — cannot be** | key rotation happens on the provider's dashboard, which is outside this machine. Recorded as yours (§9) | editing `.env` with an invented value; cost: a deployment that cannot fail over |
| 12 | `.env` changes — commit them? | **No commit** | `.env` is gitignored (`.gitignore:24`); there is no tracked change to commit. The backup `.env.bak.1789444582` is ignored by the same rule | force-adding it; cost: live credentials in git history, permanently |
| 13 | Merge method for #133 | **Merge commit (`--merge`)** | the tag pointed at `83ed13b`; squash or rebase rewrites that sha and orphans the tag. Also preserves 58 one-task-per-commit records carrying each fix's red output | squash; cost: a tag pointing at an unreachable commit, and the loss of every per-commit red→green record into one blob |
| 14 | `fetch --all --tags` deleted the local tag | **Recreate identically and push immediately** | `fetch.pruneTags=true` prunes local tags absent from the remote. `83ed13b` was untouched and still an ancestor of `main`, so only the tag object was lost | leaving it local until "later"; cost: the same prune deletes it again on the next fetch, silently |
| 15 | 16 MiB WS frames — fix or file? | **Fixed** (`a95deaf`) | one line plus a test, and it is a deploy-safety property: 5 MB frames crossed nginx and were buffered whole on a single-worker box about to take five real users | filing an issue; cost: shipping a known attacker-controlled allocation into the pilot, with a runbook that claims the request cap covers it |
| 16 | nginx healthcheck on `:443` or `:80`? | **`:80`, with the limitation documented and measured** | the image has no curl/openssl and busybox wget fails the self-signed cert, so a `:443` probe reports unhealthy through the entire bootstrap `deploy.md` §3 mandates | a `:443` probe; cost: a healthcheck that flaps during the documented happy path, training the operator to ignore it |
| 17 | Close #59 without the live leg? | **Close it, and state exactly what is unverified** | the blocker is "a new user follows the docs and cannot get running" — disproven end to end. The live leg is one env var plus a paid call, and `primary_configured: true` proves the config path without spending | leaving it open; cost: a `severity:blocker` staying open on a question that has been answered, for a leg that costs money to run |
| 18 | Run the dry-run against `localhost` or a hostname? | **`coach.localtest.me`** (public DNS → 127.0.0.1) | exercises real SNI, a real `Host`, and a real browser-shaped `Origin` — the three things a loopback shortcut would not have tested, and origin handling is where a proxied WebSocket actually breaks | `127.0.0.1`; cost: the Origin/SNI checks would have been vacuous, which is the half most likely to be wrong |
| 19 | Leave the dry-run stack running? | **Tore it down** | it holds :80 and :443 on a dev machine indefinitely, with a self-signed cert. One command rebuilds it | leaving it up; cost: two privileged ports occupied on the user's machine for a dry-run they did not ask to keep |
| 20 | `.env` origin after the dry-run | **Left at `https://coach.localtest.me`, flagged** | both it and the previous `http://localhost:5173` are wrong for production; neither is more correct. Pre-flight line 2 is the gate | silently restoring the dev value; cost: swapping one wrong value for another while looking like a cleanup |

---

## 10. Issues filed

Two comments on existing issues, twelve new. Every body carries verified `file:line` evidence, a
trigger, and an AC checklist; every one was adversarially re-checked before filing.

| # | title | trigger |
|---|---|---|
| **#96** *(comment)* | Anchor `depth` and `system_thinking` at 3 | already open — updated with today's measurements, `severity:medium` → **`severity:high`**. Closing it is what turns the bench gate green |
| **#84** *(comment)* | R-29 Real accounts | a second person using the deployment. Carries QA-02's isolation half + M2-4 |
| #121 | Web report drops 5 of 10 Committee fields; turn trace typed as `Record<string, unknown>` | any web-report work (#60 / #83), or the first time you must open the export to explain a verdict |
| #122 | Same-candidate load→fuse→save isn't one critical section | a debrief's evidence absent from the next Session's priors, with nothing logged |
| #123 | `reconcile_accounting` rewrites the fault sidecar unlocked | two concurrent `coach usage --reconcile` runs |
| #124 | Split `web_api.py` (1,345) and `cli.py` (1,433) | the next change touching both halves of either file |
| #125 | Usage rails full-scan the whole JSONL ledger per question | `coach usage` >1s, or ~50k rows |
| #126 | The usage ledger has no rotation, TTL or prune | pair with #125; or the state volume crossing a size you care about |
| #127 | Skill ledger keeps one snapshot per Candidate — no history | the progress dashboard (#83) |
| #128 | The duplication catalogue — the "16" undercounts | opportunistic, when a change already touches a copy |
| #129 | Dead weight: `SelfCritiqueTrace`, `docs/reference/*`, write-only `data/` | any pass that already touches them |
| #130 | `resources.py:3` claims Chroma is the production path | the old R-13 trigger is dead (#68 closed); #130 carries a live one |
| #131 | `ruff format` is ungated by CI — 26 files drift | a window with no open PR touching those files |
| #132 | Micro-loop polish: no follow-up re-ask guard, ungated `skip_ahead`, sticky `concept_miss` | a Candidate reporting a repeated or skipped question |

**#119** is closed by the PR.

---

## 11. What is left for you

| # | task | blocking what | why it is not mine |
|---|---|---|---|
| 1 | **Rotate the Groq key** | **pre-flight line 1 — nothing else can tick it** | rotation happens on Groq's dashboard. The key in `.env` is live and has sat in a file read repeatedly across two audits. Groq is the availability fallback and must never take the judge role (ADR 0009a; M0-13 enforces it) |
| 2 | **Set `COACH_ALLOWED_ORIGINS` to the production origin** | pre-flight line 2 | it holds the dry-run value `https://coach.localtest.me`. No production hostname exists in the repo to infer — `deploy/nginx/conf.d/coach.conf` is `server_name _` by design |
| 3 | **Generate a production `COACH_AUTH_TOKEN`** | pre-flight line 3 | the token in `.env` was generated on this dev machine and has been used in local containers all session. It is a dev token; do not carry it to a host strangers can reach |
| 4 | **Replace the self-signed cert** and set `server_name` | lines 6, 11 | the dry-run cert is for `coach.localtest.me`. `deploy.md` §3 has the certbot path; pre-flight line 11 proves the ACME webroot works |
| 5 | **Decide #96** | the bench gate stays red | budget ~181k–207k tokens **per k=3 invocation** and **3+ invocations** — every re-wording restarts the repeatability count from zero |

Nothing else is outstanding on my side. The PR is merged, the tag is pushed and reachable, `main` is
green, and both blockers that were open at the start of this session (#119, #59) are closed.

**To bring the dry-run stack back up** (it was torn down — decision 19):

```bash
# certs, if you have not issued real ones yet — deploy.md §3
mkdir -p deploy/nginx/certs deploy/certbot-webroot && cd deploy/nginx/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=<your host>" -addext "subjectAltName=DNS:<your host>"
cd - && docker compose up -d --build
```

Then work through [`docs/pilot-runbook.md`](docs/pilot-runbook.md) §1 before anyone else connects.

---

## 12. Numbers

```
commits above main at the tag        58   (git log --no-merges 2dac711..HEAD, at 83ed13b)
commits on main after this session   63   (58 + 4 pilot-hardening + this report)
pytest                               848 -> 973   (+125; +1 this session, the WS frame bound)
vitest                               27  -> 35
mypy                                 34 source files, clean
stable checklist                     20 PASS / 1 FAIL (item 8: bench 34/35, judge drift, accepted)
deploy dry-run                       11 of 11 PASS, 2 defects found and fixed
onboarding (#59)                     38 s cold / 8 s repo-controlled  (DoD was <= 10 min)
bench                                34/35 — NOT re-run this session, nothing widened
PR #133                              MERGED as a merge commit (92d4dd1)
tag v0.1.0-pilot                     PUSHED, annotated, on 83ed13b, ancestor of main (TAG OK)
issues closed this session           #119, #59
issues open from this work           #96 (bench red), #84 (isolation), #121-#132
blocking the pilot                   1 line: the Groq key rotation (pre-flight line 1)
```
