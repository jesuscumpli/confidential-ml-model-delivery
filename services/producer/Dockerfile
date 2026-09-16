# syntax=docker/dockerfile:1
# Build from the repository root so the uv workspace (shared crypto package and the
# single member lockfile) is in the build context:
#   docker build -f services/producer/Dockerfile -t producer:dev .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1

# Workspace metadata + the shared crypto package (a path dependency, so its source is
# needed to build the producer's environment). Only producer's dependency group is
# installed; the other members are present only so the workspace validates.
COPY pyproject.toml uv.lock README.md ./
COPY packages/confidential-crypto packages/confidential-crypto
COPY services/producer/pyproject.toml services/producer/README.md services/producer/
COPY services/consumer/pyproject.toml services/consumer/README.md services/consumer/
COPY benchmarks/pyproject.toml benchmarks/README.md benchmarks/
RUN uv sync --frozen --no-dev --no-install-project --package producer

COPY services/producer/src services/producer/src
RUN uv sync --frozen --no-dev --package producer

FROM python:3.12-slim-bookworm

# Debian security updates the base tag may not carry yet (Trivy gates HIGH/CRITICAL in CI).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /work && chown app:app /work
COPY --from=builder --chown=app:app /app /app

# Writable locations for the non-root user: Hub cache and the download/package/upload dir.
# The key file and HF_TOKEN are supplied at run time (mounted file / environment), never baked in.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/work/hf-cache \
    PRODUCER_WORK_DIR=/work/artifacts

USER app
WORKDIR /work
ENTRYPOINT ["producer"]
CMD ["--help"]