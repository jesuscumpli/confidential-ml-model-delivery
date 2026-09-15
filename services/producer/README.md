# producer

Encrypts and publishes Hugging Face model artifacts (Layer 1) and optionally
signs them (Layer 2) before pushing them to the Hugging Face Hub.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check
uv run mypy src
```

Stack: Python 3.12, uv, `cryptography`, `huggingface_hub`. The CLI entry point
is added at Milestone 3 (see `docs/plan.md`).