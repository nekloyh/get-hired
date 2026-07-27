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

For a real hostname, issue once on the host with certbot and point the mount at the result:

```bash
sudo certbot certonly --standalone -d coach.example.com
sudo mkdir -p deploy/nginx/certs
sudo cp /etc/letsencrypt/live/coach.example.com/{fullchain.pem,privkey.pem} deploy/nginx/certs/
```

For a staging box or a local smoke test, a self-signed pair is enough (browsers will warn):

```bash
mkdir -p deploy/nginx/certs && cd deploy/nginx/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout privkey.pem -out fullchain.pem \
  -subj "/CN=coach.example.com" -addext "subjectAltName=DNS:coach.example.com"
```

Then replace `server_name _;` in `deploy/nginx/conf.d/coach.conf` with your hostname. Renewal is a
host-side certbot timer plus `docker compose restart nginx`; nothing in the image expires.

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

A `docker restart` mid-question is recoverable: the browser shows *Connection lost*, **Reconnect**
resumes from the checkpoint, and the pending question is re-emitted. This is verified from a real
browser against a real container — see §8.

Back it up with `docker run --rm -v coach-state:/state -v "$PWD:/backup" alpine tar czf
/backup/coach-state.tgz -C /state .`

## 6. The single-worker constraint

**Do not add workers.** `runtimes` and `completed_sessions` are per-process dicts and the checkpoint
store is SQLite, so a second worker gets a resume request for a Session it has never heard of, and
two processes write the same SQLite file. `WEB_CONCURRENCY` and `--workers` are not supported; the
image's `CMD` runs one worker on purpose. (A guard that refuses to start on `WEB_CONCURRENCY>1` is
tracked as R-12/#67.) One worker handles this workload comfortably — a Session spends nearly all of
its wall time waiting on the model, and each one runs on its own thread.

Scaling past one host means R-29 (Postgres checkpointer + real accounts), not more workers.

## 7. Operating it

```bash
docker compose logs -f app          # session lifecycle + the per-call `llm-call` trace
docker compose exec app coach usage # today's token spend against the daily budget
docker compose up -d --build        # redeploy; the state volume is untouched
```

The `llm-call provider=… model=… ms=… outcome=…` line (R-26) is the one that makes a silent judge
failover visible after the fact. If you ever see the judge role on a provider it is not pinned to,
that is a bug worth reporting — ADR 0009 says the judge never fails over onto another model.

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
