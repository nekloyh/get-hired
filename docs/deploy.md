# Deploying the Adaptive Interview Coach on a single VPS

The deploy target is deliberately small: **one host, one process, one shared secret**, sized for the
handful of trusted users this project actually has. Multi-user identity and a real database are
R-29, not this document.

Two containers: `app` (the API plus the built React bundle, one origin) and `nginx` (TLS termination
and the `wss://` proxy).

---

## 1. Prerequisites

- A host with Docker and the Compose plugin (`docker compose version`).
- A DNS A record pointing at it, if you want a real certificate.
- **One OpenAI API key.** Nothing else is required: no Chroma, no second provider.

## 2. Configure

```bash
git clone https://github.com/nekloyh/get-hired.git && cd get-hired
cp .env.example .env
```

Edit `.env`. The four lines that matter for a deployment:

```dotenv
PRIMARY_PROVIDER=openai
OPENAI_API_KEY=sk-...

COACH_AUTH_TOKEN=<openssl rand -hex 32>
COACH_ALLOWED_ORIGINS=https://coach.example.com
```

| Variable | Why it matters |
| --- | --- |
| `COACH_AUTH_TOKEN` | **Unset means open.** Every endpoint, to anything that can reach the port. Must be ASCII — HTTP header values are latin-1 on the wire, so a non-ASCII passphrase cannot round-trip through `Authorization: Bearer`, and the server refuses to start rather than lock you out of your own deployment with unexplained 500s. |
| `COACH_ALLOWED_ORIGINS` | Comma-separated browser origins allowed to open a Session socket, checked **before** the WebSocket is accepted. `CORSMiddleware` cannot do this — it never sees a WebSocket handshake. Leave it empty and the socket falls back to the Vite dev origins, i.e. it will reject your own UI (the server warns about this at startup). |
| `OPENAI_MODEL` | Defaults to `gpt-5.4-mini`, the judge this project is calibrated against. Changing it is a **judge change** and is gated by `coach bench` (ADR 0009) — do not "upgrade" it on a whim in production. |
| `LLM_DAILY_TOKEN_BUDGET` | The provider does not expose a daily allowance, so spend is counted client-side. Worth setting before strangers can start interviews on your key. |

The UI asks for `COACH_AUTH_TOKEN` at runtime and keeps it in `sessionStorage`. There is deliberately
**no build-time token**: Vite inlines `VITE_*` constants into the emitted JavaScript, so a token
baked at build time is readable by anyone who can fetch the app it is supposed to gate.

## 3. Certificates

**Bootstrap first, then issue.** nginx refuses to start without a certificate file (`cannot load
certificate "/etc/nginx/certs/fullchain.pem"`), and certbot's http-01 challenge is served *by*
nginx — so the self-signed pair is not just the staging path, it is step one of the real one:

```bash
mkdir -p deploy/nginx/certs deploy/certbot-webroot && cd deploy/nginx/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=coach.example.com" -addext "subjectAltName=DNS:coach.example.com"
cd -
```

Replace `server_name _;` in `deploy/nginx/conf.d/coach.conf` with your hostname, bring the stack up
(§4), and only then issue the real certificate — over the webroot nginx already serves, **not**
`--standalone`:

```bash
# /srv/coach is this checkout's absolute path; substitute yours in all three places. The
# --deploy-hook value must stay on one line.
sudo certbot certonly --webroot -w /srv/coach/deploy/certbot-webroot \
  -d coach.example.com \
  --deploy-hook 'cp "$RENEWED_LINEAGE/fullchain.pem" "$RENEWED_LINEAGE/privkey.pem" /srv/coach/deploy/nginx/certs/ && docker compose -f /srv/coach/docker-compose.yml restart nginx'
```

`--standalone` cannot work here and must not be used: it binds :80 itself, and the nginx container
holds :80 for the life of the deployment. It would fail at issuance and — worse — `certbot renew`
replays whatever authenticator issuance recorded, so a certificate issued with `--standalone`
renews with `--standalone`: failing from ~day 60 and hard-expiring at day 90, taking `wss://` down
with `https://`, because the UI's WebSocket inherits the page scheme.

The hook is what makes renewal actually land: nginx serves *copies* under `deploy/nginx/certs/`, so
a renewal that only rewrites `/etc/letsencrypt/live/…` and restarts nginx re-serves the expired
copy. Certbot saves `--deploy-hook` into `/etc/letsencrypt/renewal/coach.example.com.conf`, so the
packaged `certbot.timer` needs no further configuration. Two details are load-bearing: the hook runs
with no useful cwd, so every path in it is absolute; and both `.pem` files are named, because
certbot runs hooks through `/bin/sh`, which does not expand `{a,b}`.

Verify before you depend on it: `sudo certbot renew --dry-run` with the stack **up**. It exercises
the webroot for real; it does *not* run deploy hooks, so also confirm the ACME location is
reachable: `curl -si -H 'Host: coach.example.com' http://<host>/.well-known/acme-challenge/probe` —
a 404 from *nginx* is correct, a 301 to `https://` means the location is not matching.

## 4. Run

```bash
docker compose up -d --build
docker compose ps          # app should read "healthy"
curl -sk https://coach.example.com/api/health
```

`https://coach.example.com/` serves the UI and the API from one origin. That is not a packaging
convenience — same-origin is what lets one image run behind any hostname (the bundle has no baked-in
API URL), makes `wss://` follow `https://` without configuration, and leaves no cross-origin
handshake for CORS or the Origin allowlist to adjudicate.

## 5. What survives a restart, and what does not

The `coach-state` volume holds everything that must outlive the process:

| Path | What it is | Lost if the volume is lost |
| --- | --- | --- |
| `/app/state/session-checkpoints.sqlite` | LangGraph checkpoints | Every in-flight interview; resume stops working |
| `/app/state/exports/` | Completed-Session Markdown (R-08) | Every report not already downloaded |
| `/app/state/skill-ledger.json` | Cross-session Beta priors | Returning Candidates cold-start again |
| `/app/state/usage-ledger.jsonl` | The token ledger — i.e. the free-tier budget balance | The day's spend resets to zero and every budget rail over-reports |

A `docker restart` mid-question is recoverable: the browser shows *Connection lost*, **Reconnect**
resumes from the checkpoint, and the pending question is re-emitted. This is verified from a real
browser against a real container — see §8.

Back it up **outside the checkout**:

```bash
sudo install -d -m 700 /var/backups/coach
docker compose run --rm --no-deps --user root -v /var/backups/coach:/backup app \
  tar czf "/backup/coach-state-$(date +%F).tgz" -C /app/state .
```

`docker compose run` is what makes this correct: Compose names the volume `<project>_coach-state`,
so a hand-written `docker run` that mounts `coach-state` by its bare key mounts a *different*
volume — one Docker silently creates, empty — and tars nothing. Running it as the `app` service
borrows the mount that service already has. The destination is off the checkout on purpose: `$PWD`
is the git working tree and the Docker build context, and the archive is every Candidate's
transcript plus both ledgers — no `.gitignore` rule covers it, so `git add -A` on the deploy host
would publish it. A dated name keeps one bad run from overwriting the only copy; copy it to another
host to make it a backup.

## 6. The single-worker constraint

**Do not add workers.** `runtimes` and `completed_sessions` are per-process dicts and the checkpoint
store is SQLite, so a second worker gets a resume request for a Session it has never heard of, and
two processes write the same SQLite file. `WEB_CONCURRENCY` and `--workers` are not supported; the
image's `CMD` runs one worker on purpose. **The server now refuses to start** on `WEB_CONCURRENCY>1`
or `--workers >1` (R-12) — the check runs when `interview_coach.web_api` is imported, so under
`coach api` and `uvicorn …:app` it fires before a port is bound: uvicorn's `config.load_app()` runs
ahead of `bind_socket()` and `Multiprocess(...)`. It resolves a repeated `--workers` the way uvicorn
does (last one wins), and an explicit `--workers` shadows `WEB_CONCURRENCY`, because a guard that
reads the command line differently from the launcher both misses and misfires.
It matches the long form `--workers` only; the short `-w` is not sniffed, because `-w` means
something else in too many other commands to claim on sight.
Scope: **gunicorn is not covered.** It is not a dependency and not in the image, and its default
`preload_app=False` binds the port and logs `Listening at:` *before* forking and importing the app —
so the guard would fire in the children, after the port was already bound. Run this app under
uvicorn.
`WEB_CONCURRENCY` is the one that bites without being typed: `docker-compose.yml` passes `.env`
through wholesale and uvicorn reads the variable itself. One worker handles this workload comfortably
— a Session spends nearly all of its wall time waiting on the model, and each one runs on its own
thread.

Scaling past one host means R-29 (Postgres checkpointer + real accounts), not more workers.

## 7. Operating it

```bash
docker compose logs -f app          # session lifecycle + the per-call `llm-call` trace
docker compose exec app coach usage # today's token spend + the accounting health line
docker compose exec app coach usage --reconcile  # replay rows a failed ledger write parked
docker compose up -d --build        # redeploy; the state volume is untouched
```

`coach usage` leads with an **ACCOUNTING:** line whenever the token ledger cannot be written or is
holding rows a failed write could not land. Take it seriously: every number that command prints —
and every budget rail in the app — is arithmetic over `/app/state/usage-ledger.jsonl`, so a ledger
nobody can write reads as a *full* budget rather than an unknown one. That is not theoretical: until
M0a the image left `COACH_USAGE_LEDGER` at its repo-anchored default, which resolves to
`/app/logs/usage-ledger.jsonl` inside the container, and `/app` is `root:root` 755 while the process
is uid 10001 — so every append failed, every token row was dropped with a warning, and the
deployment reported a pristine 2,500,000-token allowance for as long as it ran.

Two conditions, with different remedies, and the message says which:

- **unavailable** — the path cannot be written. Nothing is unaccounted for, because metered calls
  are refused while it holds; point `COACH_USAGE_LEDGER` at the state volume and it clears itself.
- **UNRECONCILED** — a provider call was billed and its usage row would not write. The day's spend
  is now *undetermined*, which is not zero. The unwritten rows are parked in
  `/app/state/usage-ledger.jsonl.unreconciled`; fix the path, then
  `docker compose exec app coach usage --reconcile` replays them into the ledger and clears it.

Either way metered work stops and demo mode keeps working, so a misconfigured deployment is
demonstrable rather than dead. Suspended Sessions keep their resolved questions in the checkpoint
and record nothing as `failed` (ADR 0005).

The `llm-call provider=… model=… ms=… outcome=…` line (R-26) is the one that makes a silent judge
failover visible after the fact. If you ever see the judge role on a provider it is not pinned to,
that is a bug worth reporting — ADR 0009 says the judge never fails over onto another model.

Server logs are INFO by default and go to stderr, which `docker compose logs` shows but a container
restart discards. To keep them, `docker-compose.yml` sets `COACH_LOG_FILE=/app/state/logs/coach-api.log`
in its `environment:` block — it rotates at 10 MB and keeps 5 files. The path **must** be on the
state volume: `/app` is `root:root` 755 and the container runs as uid 10001 `coach`, so anything
else fails `mkdir` and degrades to stderr-only. That is why the value is set there rather than left
to `.env`, whose copy of the key is a host path for a local checkout (`coach api --log-file …`).
An unwritable path degrades to stderr with a warning rather than refusing to start; losing the log
is not worth losing the deployment — but it does mean a wrong path is quiet, so check for
`is not writable` in the first lines of `docker compose logs app`.
Lifecycle records to grep for: `Session '…' socket connected`, `Session '…' finished: status=…`,
and `Session '…' cancelled by Candidate intent`.

## 8. Verified, not asserted

Every claim above was executed against real containers on 2026-07-27:

- `docker build` → image builds; `docker compose up -d` → `app` healthy, `nginx` up.
- `http://` → **301** to `https://`; `https://` → UI (HTTP 200) and `/api/health` on one origin.
- A demo Session completed over **`wss://` through nginx** with the self-signed certificate.
- **`docker restart` mid-question**: question pending and unanswered → restart → resume re-emitted
  the same question → answered → Session completed, with the post-restart answer in the transcript.
- An export written **before** the restart was still served afterwards from the volume.
- The Playwright reconnect spec passed pointed at the container:
  `npm run test:e2e:container` (stops and starts the container instead of a local process).

§6 and §7 were re-executed on 2026-08-01, against real uvicorn 0.48.0 and the real image
(source bind-mounted over `/app/src`, which the image installs editable):

- `uvicorn --workers 1 --workers 4 …:app` → refused, **zero** `Started server process` lines. The
  mirror `--workers 4 --workers 1` → starts, one process: the guard follows uvicorn's own
  last-one-wins resolution rather than a guess. (`uvicorn.main.main.make_context(...)`
  `.params["workers"]` returns 4 and 1 respectively; `main.run()` calls `config.load_app()` before
  `config.bind_socket()`, which is what makes "before the port" true.)
- `docker run -e WEB_CONCURRENCY=4 <image>` (the image's own `CMD`) → **exit 2**, the guard's
  message, no traceback, no port bound.
- `docker run -e COACH_LOG_FILE=logs/coach-api.log <image>` — the value `.env.example` used to
  suggest — → `PermissionError: [Errno 13] Permission denied: 'logs'`, degraded to stderr-only.
  `/app` is `root:root` 755 and the process is uid 10001. With `/app/state/logs/coach-api.log` on
  the volume the directory is created and the `llm-call` line is in the file.
- `docker compose config` with that same `COACH_LOG_FILE=logs/coach-api.log` in `.env` →
  `COACH_LOG_FILE: /app/state/logs/coach-api.log`: the `environment:` block overrides `env_file`.
- gunicorn is **not** verified and not covered — see §6.

The usage-accounting path (M0a / F1) was executed on 2026-09-13 against the real image, as uid
10001, on disposable volumes. Fakes are limited to the HTTP transport: the real `OpenAIClient`, its
real call path and the real `record_usage` run, so no paid API is contacted. Full report and
commands: [`docs/audits/m0a-usage-ledger-2026-09-13.md`](audits/m0a-usage-ledger-2026-09-13.md).

- **The defect, reproduced:** pre-fix `usage.py`/`llm.py` mounted over the image with
  `COACH_USAGE_LEDGER` unset → 3 fake metered calls made, **0** ledger rows,
  `remaining_today = 2,500,000`, exit 0, three `usage ledger write failed … dropping entry`
  warnings. `mkdir /app/logs` as uid 10001 → `PermissionError`.
- **Fixed image, stock config:** one fake metered call → exactly one row in
  `/app/state/usage-ledger.jsonl`, balance 2,500,000 → 2,499,880.
- **Survives restart and container replacement:** 5 calls / 600 tokens, then `docker restart`, then
  `docker rm` + a fresh container from the image on the same volume → same 600 tokens both times.
- **Unwritable path:** `/app/logs/usage-ledger.jsonl` (the old default) → `AccountingUnavailable`,
  **zero** provider calls made, `coach session` refuses with exit 2 and names the remedy.
- **Failure after a billed call:** ledger replaced by a directory mid-run → the billed call's row is
  parked in `usage-ledger.jsonl.unreconciled`, the next call is refused, repairing the path alone
  does **not** clear it, and `--reconcile` replays the 120 tokens back into the ledger.
- **Unchanged:** the daily-budget start rail still refuses with its own wording, and a demo Session
  completes with no provider configured *and* a deliberately unwritable ledger.
- `docker compose config` with `COACH_USAGE_LEDGER=logs/usage-ledger.jsonl` in `.env` →
  `/app/state/usage-ledger.jsonl`: the `environment:` block overrides `env_file`, and the container
  reads the winning value.
