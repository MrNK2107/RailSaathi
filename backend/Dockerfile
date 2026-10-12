# RailSaathi AI backend. Multi-stage: resolve dependencies with uv, run as a non-root user.
# Build:  docker build -t railsaathi-backend ./backend
# Run:    docker run --rm -p 8080:8080 -e RAILWAY_DATA_MODE=demo railsaathi-backend

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first so this layer is cached independently of source changes.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY data ./data


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080 \
    APP_ENV=production

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/api/health', timeout=4)" || exit 1

# One worker per container: Cloud Run scales by adding instances. Sessions are still in-process
# until Phase 2 (Redis), so the Phase 1 service runs with max-instances=1.
CMD ["sh", "-c", "exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
