# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim as base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1
# Unbuffered logs (good for containers)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Create non-root user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Install deps with caching
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=/app/requirements.txt \
    python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy source
COPY . /app

# Default envs (override in docker-compose)
ENV OUTPUT_DIR=/data \
    OUTPUT_FORMAT=parquet \
    OUTPUT_BASENAME=transactions

# Create writable output dir and set permissions for non-root user
USER root
RUN mkdir -p /data && chown -R appuser:appuser /data

# Run as non-root
USER appuser

# Optional: document the mount point
VOLUME ["/data"]

# Batch job entrypoint
CMD ["python", "generator.py"]