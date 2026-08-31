# syntax=docker/dockerfile:1

# ---- spa: build the React bundle ----
# vite.config.ts writes to ../agentaudit/web/spa_dist, so the whole frontend/
# tree is copied in and the output lands at frontend/agentaudit/web/spa_dist.
# spa_dist is gitignored, so without this stage pip packages no bundle at all
# and the served dashboard is app.py's "not built yet" placeholder.
FROM node:22-slim AS spa

WORKDIR /build
COPY frontend ./frontend
WORKDIR /build/frontend/spa
RUN npm ci && npm run build

# ---- builder: install deps and the package into a venv ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m venv "$VIRTUAL_ENV"

# Copy metadata first so dependency install is cached independently of source.
COPY pyproject.toml README.md ./
COPY agentaudit ./agentaudit
COPY backend ./backend
COPY frontend ./frontend
COPY infra/alembic ./infra/alembic

# Overlay the built bundle so setuptools package-data picks it up.
COPY --from=spa /build/frontend/agentaudit/web/spa_dist ./frontend/agentaudit/web/spa_dist

RUN pip install .

# ---- runtime: slim image with just the venv and package ----
FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTAUDIT_DB=/data/agentaudit.db \
    AGENTAUDIT_PACKS=/opt/venv/lib/python3.12/site-packages/agentaudit/packs

# Non-root user; /data holds the sqlite db as a mountable volume.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app

# Everything (code, templates, static, packs) ships inside the installed wheel.
# Do not add the SPA sources here: app.py's stale-bundle banner compares source
# mtimes against the build and would fire on every page in the container.
COPY --from=builder /opt/venv /opt/venv

USER app
VOLUME ["/data"]
EXPOSE 8000

# Serve the dashboard; bind to 0.0.0.0 so it's reachable outside the container.
CMD ["agentaudit", "ui", "--host", "0.0.0.0", "--port", "8000"]
