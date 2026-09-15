# syntax=docker/dockerfile:1
# Build from the repository root so the shared crypto package is in context:
#   docker build -f services/producer/Dockerfile -t producer:dev .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app/services/producer
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY packages/confidential-crypto /app/packages/confidential-crypto
COPY services/producer/pyproject.toml services/producer/uv.lock services/producer/README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY services/producer/src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/services/producer/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
WORKDIR /app/services/producer
CMD ["python", "-m", "producer"]
