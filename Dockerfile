# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml .

# Install dependencies into /app/.venv (no dev deps)
RUN uv sync --no-dev --frozen || uv sync --no-dev

# ── final stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the venv from the builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY . .

# Ensure the venv's bin directory is on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Railway injects $PORT; fall back to 8000 for local dev.
EXPOSE ${PORT:-8000}
CMD ["python", "bot.py"]
