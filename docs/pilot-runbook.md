# Pilot runbook — before you let five real people in

This is the gate between a deployment that *runs* and one that is safe to hand to people.
[`docs/deploy.md`](deploy.md) tells you how to stand the stack up; this tells you what must be true
before anyone else touches it, what you have to say out loud to the people using it, and what to do
when something goes wrong.

Scope: `v0.2.0` (and `v0.1.0-pilot` before it — nothing here changed between them). **Trusted pilot, not a public launch** — the difference is not a
feature list, it is that every person with the token is trusted with every other person's data. §2
is not a disclaimer; it is the deployment's actual security model.

---

## 1. Pre-flight — every line is one command with a binary answer

Run these **on the deploy host**, against the real hostname, after `docker compose up -d`. Do not
skip a line because it "was fine last time": three of these are one-character mistakes that leave
the deployment looking healthy.

| # | Check | Command | Pass |
|---|---|---|---|
| 1 | **Groq key rotated** | — (provider dashboard) | the key in `.env` is one that has never been in a git checkout, a chat log, or an audit transcript |
| 2 | Production origin, not localhost | `grep '^COACH_ALLOWED_ORIGINS=' .env` | `https://<your real host>` — **not** `http://localhost:5173`, not `*` (refused at startup), not `http://` |
| 3 | Production token, freshly generated | `grep -c '^COACH_AUTH_TOKEN=.\{32,\}' .env` | `1`, and its value was generated **for this host** — not reused from a dev `.env` |
| 4 | No dead MiMo keys | `grep -c '^MIMO_' .env` | `0` |
| 5 | Both containers healthy | `docker compose ps` | `app` **healthy** and `nginx` **healthy** (see the caveat below) |
| 6 | TLS serves and the upstream is reachable | `curl -s https://<host>/api/health` | `"status":"ok"` and `"auth_required":true` |
| 7 | Plain HTTP cannot be used by accident | `curl -s -o /dev/null -w '%{http_code}' http://<host>/api/health` | `301` |
| 8 | The gate is actually closed | `curl -s -o /dev/null -w '%{http_code}' https://<host>/api/sessions/x/export.md` | `401` |
| 9 | The gate opens for the right token | `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" https://<host>/api/sessions/x/export.md` | `404` — not `401` (a `401` here means the token you handed out is not the token the server loaded) |
| 10 | The socket refuses a foreign origin | see §1.1 | handshake `HTTP 403` |
| 11 | Cert renewal can work in 90 days | `echo tok > deploy/certbot-webroot/.well-known/acme-challenge/t && curl -s http://<host>/.well-known/acme-challenge/t` | prints `tok` — **not** a 301. If this redirects, http-01 renewal will fail silently three months from now |
| 12 | The first backup exists and restores | §4 | an archive outside the checkout, **and** a test restore that serves the same export md5 |

**Caveat on line 5.** `nginx healthy` proves nginx is listening and `coach.conf` loaded. It does
**not** prove TLS serves or that the upstream is up — the image has neither `curl` nor `openssl`, and
busybox `wget` follows the 301 into TLS and fails certificate verification, so a `:443` probe would
report unhealthy throughout the self-signed bootstrap that `deploy.md` §3 requires. Measured: with
`app` stopped, `nginx` still reads healthy while `https://…/api/health` returns **502**. Lines 6–9
are what cover that gap, which is why they are run against the real hostname and not `127.0.0.1`.

### 1.1 The origin check

```bash
# Replace <host>. Needs `websockets` (uv run --no-sync python, or any venv with it).
python - <<'EOF'
import asyncio, json, ssl, websockets
HOST, TOKEN = "<host>", "<token>"
CTX = ssl.create_default_context()          # real cert: leave verification ON
async def probe(origin):
    try:
        ws = await websockets.connect(f"wss://{HOST}/api/sessions/preflight", origin=origin, ssl=CTX)
        await ws.send(json.dumps({"type": "auth", "token": TOKEN}))
        await ws.send(json.dumps({"type": "resume_session", "mode": "demo"}))
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=20)); await ws.close()
        return f"ACCEPTED ({m.get('type')})"
    except Exception as e:
        return f"REFUSED {type(e).__name__}: {str(e)[:60]}"
async def main():
    for o in [f"https://{HOST}", "https://evil.example.com", f"http://{HOST}", "null"]:
        print(f"  {o:34} -> {await probe(o)}")
asyncio.run(main())
EOF
```

Only the first line may say `ACCEPTED`. Everything else must be `HTTP 403` at the handshake —
including the `http://` variant of your own host, because the scheme is part of an origin.

---

## 2. What you must tell every pilot user

Say these in words they will act on. All four are properties of the release, not bugs to be
worked around.

### One token, no privacy between you

Everyone shares one password to the whole installation. There is no per-person account. Concretely:

- **Anyone who has the link and the token can read and overwrite anyone else's saved skill
  history**, just by typing that person's Candidate id. The id is not a secret and is not checked
  against who you are.
- **Anyone can open, resume, cancel, or download any interview report** whose Session id they can
  guess or are shown.

This is why it is called a *trusted pilot*: pick people who would be allowed to read each other's
practice interviews anyway. Do not use a personal id you use elsewhere, and do not put anything in
an answer you would not show the whole group. (GH #84 is the work that fixes this.)

### The daily cap is shared, not per person

**480 questions per day for the entire deployment** — roughly 48 ten-question interviews *across
everybody*. One person doing long sessions all morning can exhaust the day for the other four. If a
session refuses to start with a cap message, that is this, not a fault.

### A crash loses the current question, not the interview

Resume works at the **question** level, not the turn. If the server restarts while someone is
mid-question, the follow-up they already answered inside that question is gone and the question is
re-asked from the top. Everything completed before it is safe. (Verified: restart mid-question →
the same question is re-issued → the post-restart answer lands in the report.)

### The scores are for practice, not for judging anyone

The grader is an LLM whose calibration is **known to have drifted**, and the calibration gate is
currently **red at 34/35** (`docs/audits/calibration-bench-2026-09-15.md`, GH #96). One known effect:
Vietnamese answers can score higher than the identical English answer, because two rubric dimensions
have a gap in their scale. Use the feedback to practise. **Do not use these scores to compare
people, and do not put them in front of a recruiter as a measurement.**

---

## 3. Running it day to day

Commands, log lines to grep for, and the `ACCOUNTING:` conditions are in
[`docs/deploy.md` §7](deploy.md) — that is the reference, not repeated here. What follows is only
what a pilot operator needs on top.

### Where to look first

```bash
docker compose ps                      # both must be healthy — see the §1 caveat on nginx
docker compose logs -f app             # session lifecycle + the per-call `llm-call` trace
docker compose exec app coach usage    # today's spend, and the ACCOUNTING: health line
```

### When one person's session is stuck

Symptoms and what they mean:

| What they report | What to check | What to do |
|---|---|---|
| "It says the previous run is still finishing" | `docker compose logs app \| grep 'still finishing'` clustered on one Session id | a provider stall holds the runtime up to ~4 min. Tell them to wait, not to retry-storm |
| "It just stopped" right after typing fast | `grep 'Answer refused'` | answers are bound to the question they were typed for; the refusal is the guard working. Reload and re-answer |
| The browser never connects at all | `docker compose logs nginx`, then pre-flight line 10 | almost always `COACH_ALLOWED_ORIGINS` not matching the origin the browser actually sends |
| A session cannot start, cap message | `docker compose exec app coach usage` | the shared 480/day is spent. It resets on the UTC day |
| `coach usage` leads with `ACCOUNTING:` | `deploy.md` §7 | **unavailable** → fix the path. **UNRECONCILED** → fix the path, then `coach usage --reconcile` |

### Restarting

`docker compose restart app` is safe mid-interview and takes about a second. A Candidate with a
question open reconnects and is re-asked that question; completed questions are untouched.
`docker compose up -d --build` redeploys without touching the state volume.

---

## 4. Backup and restore — both halves, verified

The state volume is the interviews. Losing it loses every in-flight session, every report not yet
downloaded, and everyone's cross-session skill history.

**Back up** (from the checkout, as `deploy.md` §5 specifies — `docker compose run` is load-bearing,
because a hand-written `docker run` mounting `coach-state` by its bare key silently creates a
*different*, empty volume and tars nothing):

```bash
sudo install -d -m 700 /var/backups/coach
docker compose run --rm --no-deps --user root -v /var/backups/coach:/backup app \
  tar czf "/backup/coach-state-$(date +%F).tgz" -C /app/state .
```

**Restore, and prove it restored** — a backup you have never restored is a hope, not a backup:

```bash
docker volume create coach-restore-test
docker run --rm --user root -v coach-restore-test:/app/state -v /var/backups/coach:/backup:ro \
  <image> sh -c 'tar xzf /backup/coach-state-<DATE>.tgz -C /app/state && chown -R 10001:10001 /app/state'
docker run -d --name coach-restored -p 18110:8000 --env-file .env -v coach-restore-test:/app/state <image>
curl -s -H "Authorization: Bearer $TOKEN" localhost:18110/api/sessions/<known-id>/export.md | md5sum
docker rm -f coach-restored && docker volume rm coach-restore-test
```

The `chown -R 10001:10001` is required: `tar` restores the archive's ownership, the container runs as
uid 10001, and without it the app cannot write the volume it just restored.

Executed on 2026-09-15 against the real image: archive → empty volume → new container → both known
exports served **HTTP 200 with byte-identical md5s** (`e848a3c8…`, `f0cb41f4…`).

**Note** `usage-ledger.jsonl` will not be in the archive until the deployment has made its first
metered call — demo-mode traffic creates no rows. Once live, it is in the archive and it matters:
that file **is** the budget balance, so restoring without it resets the day's spend to zero.

---

## 5. What is not covered, and what would have to change

| Not covered | Why it is acceptable for a pilot | What it would take |
|---|---|---|
| Per-user auth / per-record ownership | five trusted people | GH #84 (R-29) |
| Per-turn resume | a crash costs one question, not the interview | M1/F4 |
| Skill history over time | one snapshot per Candidate | GH #127, then #83 |
| A green judge gate | scores are framed as practice (§2) | GH #96 |
| Load, latency or cost SLO | one shared 480/day cap is the only rail | — |
| Browser E2E in CI | the WebSocket path is covered by the dry-run above | — |
| Operations dashboard | `docker compose logs` + `coach usage` | deferred |
