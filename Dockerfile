# syntax=docker/dockerfile:1

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
COPY agentkit ./agentkit

RUN pip install .

# ---- runtime: slim image with just the venv and package ----
FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTKIT_DB=/data/agentkit.db \
    AGENTKIT_PACKS=/opt/venv/lib/python3.12/site-packages/agentkit/packs

# Non-root user; /data holds the sqlite db as a mountable volume.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app

# Everything (code, templates, static, packs) ships inside the installed wheel.
COPY --from=builder /opt/venv /opt/venv

USER app
VOLUME ["/data"]
EXPOSE 8000

# Serve the dashboard; bind to 0.0.0.0 so it's reachable outside the container.
CMD ["agentkit", "ui", "--host", "0.0.0.0", "--port", "8000"]
