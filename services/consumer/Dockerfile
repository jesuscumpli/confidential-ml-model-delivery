# syntax=docker/dockerfile:1
# Build from the repository root so the uv workspace (shared crypto package and the
# single member lockfile) is in the build context:
#   docker build -f services/consumer/Dockerfile -t consumer:dev .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1

# Workspace metadata + the shared crypto package (a path dependency, so its source is
# needed to build the consumer's environment). Only consumer's dependency group is
# installed (CPU-only torch comes from the pytorch-cpu index pinned in uv.lock).
COPY pyproject.toml uv.lock README.md ./
COPY packages/confidential-crypto packages/confidential-crypto
COPY services/consumer/pyproject.toml services/consumer/README.md services/consumer/
COPY services/producer/pyproject.toml services/producer/README.md services/producer/
COPY benchmarks/pyproject.toml benchmarks/README.md benchmarks/
RUN uv sync --frozen --no-dev --no-install-project --package consumer

COPY services/consumer/src services/consumer/src
RUN uv sync --frozen --no-dev --package consumer

FROM python:3.12-slim-bookworm

# Debian security updates the base tag may not carry yet (Trivy gates HIGH/CRITICAL in CI).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /work && chown app:app /work
COPY --from=builder --chown=app:app /app /app

# /work is the only writable location (emptyDir in Kubernetes); the key arrives as a
# mounted Secret file at CONSUMER_KEY_PATH and is never part of the image or environment.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/work/hf-cache \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    CONSUMER_WORK_DIR=/work/consumer \
    CONSUMER_KEY_PATH=/etc/model-key/key \
    CONSUMER_PUBLIC_KEY_PATH=/etc/model-public-key/signing.pub

USER app
WORKDIR /work
ENTRYPOINT ["consumer"]