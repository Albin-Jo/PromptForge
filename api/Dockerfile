# syntax=docker/dockerfile:1
#
# Multi-stage build for the PromptForge API.
#   builder  — resolves + installs deps into /app/.venv with uv (never shipped)
#   runtime  — a clean slim image carrying only that venv, run as a non-root user
#
# Build context is the MONOREPO ROOT (see docker-compose.yml `context: .`), so
# paths below are relative to the repo root, not to api/.

# ---- Builder ---------------------------------------------------------------
FROM python:3.13-slim AS builder

# uv is our resolver/installer. Copied from the official image so it never has
# to be pip-installed. NOTE: `latest` is fine here because reproducibility of
# *our* dependencies is guaranteed by uv.lock + --frozen below; pin this tag if
# you want the build tool itself locked too.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Compile .pyc on install (faster cold start); copy (not symlink) into the venv
# so it can be lifted out into the runtime stage cleanly.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 1) Dependency layer — copy ONLY the manifests + lockfile, then install deps
#    WITHOUT the project source. This layer is cached until a manifest or the
#    lock changes, so editing Python code rebuilds in seconds.
#    All workspace members' manifests are copied because uv reads the whole
#    workspace from the root pyproject before scoping to --package.
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
COPY sdk/pyproject.toml sdk/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package promptforge-api

# 2) Project layer — now bring in the api source and install the package itself
#    as a wheel (--no-editable) so the runtime stage needs only the venv, not
#    the source tree on PATH.
COPY api/src api/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package promptforge-api

# ---- Runtime ---------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Unprivileged user — the app never needs root.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

# Lift the fully-resolved virtualenv out of the builder and put it first on PATH
# so `uvicorn`/`python` resolve to the venv.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Ship the Alembic config + migration scripts so this image can apply the schema
# (`alembic upgrade head`) — the compose `migrate` one-shot runs exactly that before
# the api/worker start. alembic.ini resolves the scripts via %(here)s/migrations, so
# both must sit together at the WORKDIR; the DSN is injected at runtime by env.py from
# Settings (never baked in). alembic itself is a runtime dependency (api/pyproject.toml).
COPY --chown=app:app api/alembic.ini ./alembic.ini
COPY --chown=app:app api/migrations ./migrations

USER app

EXPOSE 8000

# Bind 0.0.0.0 (NOT 127.0.0.1) so the port is reachable from other containers
# on the compose network.
CMD ["uvicorn", "promptforge_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
