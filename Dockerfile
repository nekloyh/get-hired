# syntax=docker/dockerfile:1
#
# One image serving both the React UI and the API on a single origin (R-11).
#
# Same-origin is a deployment decision, not a packaging convenience: it means the bundle carries no
# baked-in API host (so this image runs behind any hostname), the WebSocket inherits the page's
# scheme (`wss://` follows `https://` for free), and no cross-origin handshake exists for CORS or
# the R-07 Origin allowlist to adjudicate.

# --- stage 1: build the React bundle ------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web

# Manifests first so this layer is cached until a dependency actually changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# Deliberately no VITE_API_URL and no VITE_* token. A URL here would make the image host-specific;
# a token here would be published, because Vite inlines VITE_* constants into the emitted JS where
# anyone who can fetch the app can read them back out (see R-07). The UI asks for its token at
# runtime instead.
RUN npm run build


# --- stage 2: python runtime --------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies before source: editing a Python file must not re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY data/ ./data/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY --from=web /web/dist ./web/dist

# Runtime state lives in one directory so a single volume mount survives `docker restart` — the
# checkpoint DB is what makes a mid-question restart resumable rather than a lost interview, and the
# exports are the Candidate's report (R-08).
RUN mkdir -p /app/state /app/state/exports \
    && useradd --create-home --uid 10001 coach \
    && chown -R coach:coach /app/state
USER coach

ENV PATH="/app/.venv/bin:$PATH" \
    COACH_STATIC_DIR=/app/web/dist \
    COACH_CHECKPOINT_DB=/app/state/session-checkpoints.sqlite \
    COACH_LEDGER_DB=/app/state/skill-ledger.json \
    COACH_EXPORTS_DIR=/app/state/exports

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Single worker, not a default worth tuning: `runtimes` and `completed_sessions` are per-process
# dicts and the checkpoint DB is SQLite, so a second worker would route a resume to a process that
# has never heard of the Session. Documented in docs/deploy.md; the guard itself is R-12.
CMD ["coach", "api", "--host", "0.0.0.0", "--port", "8000"]
