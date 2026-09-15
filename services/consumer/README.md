# consumer

Retrieves encrypted Hugging Face model artifacts from the Hub, verifies the
Layer 2 signature, decrypts with the key stored in a Kubernetes Secret
(Layer 1), and loads the model for inference. Runs as a Kubernetes workload.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check
uv run mypy src
```

Stack: Python 3.12, uv, `cryptography`, `huggingface_hub`, `transformers`.
The consumer flow starts at Milestone 4 (see `docs/plan.md`).