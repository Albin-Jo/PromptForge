# syntax=docker/dockerfile:1
#
# Multi-stage build for the PromptForge Celery worker. Mirrors api/Dockerfile
# (ADR 0002): a builder stage resolves deps into /app/.venv with uv, and a clean
# slim runtime carries only that venv, run as a non-root user.
#
# Build context is the MONOREPO ROOT (see docker-compose.yml `context: .`), so
# paths below are relative to the repo root, not to worker/.

# ---- Builder ---------------------------------------------------------------
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 1) Dependency layer — copy ONLY the manifests + lockfile, then install the
#    worker's deps WITHOUT its source, so editing code rebuilds in seconds.
#    All workspace manifests are copied because uv reads the whole workspace from
#    the root pyproject before scoping to --package.
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
COPY sdk/pyproject.toml sdk/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package promptforge-worker

# 2) Project layer — bring in the worker source and install the package as a wheel
#    (--no-editable) so the runtime stage needs only the venv, not the source tree.
COPY worker/src worker/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package promptforge-worker

# ---- Runtime ---------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Unprivileged user — the worker never needs root.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

USER app

# No port: the worker is a queue consumer, not a server. Pool (threads), concurrency and
# queue topology come from celery_app config; -Q makes this one worker drain all three
# queues (prod can instead run a dedicated worker per queue, e.g. -Q evals).
CMD ["celery", "-A", "promptforge_worker.celery_app", "worker", \
     "--loglevel=INFO", "-Q", "celery,evals,scans"]
