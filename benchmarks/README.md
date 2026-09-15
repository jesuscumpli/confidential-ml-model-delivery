# benchmarks

Crypto evaluation phase (`docs/plan.md`, Milestone 2b). Measures every cipher and
signature scheme registered in `confidential-crypto`, combines the numbers with a
sourced security scorecard (`src/bench/scorecard.yaml`) and exports the decision
record to `docs/crypto-evaluation.md`.

```bash
uv sync

# Interactive: open notebooks/crypto_evaluation.ipynb
uv run jupyter lab notebooks

# Headless: measure, then render the ADR
uv run bench run --sizes 1 16 64 --repeats 5          # writes results/*.csv
uv run bench run --artifact ../artifacts/model.tar     # add the real artifact size
uv run bench export                                    # writes ../docs/crypto-evaluation.md

# Quality gates
uv run ruff check . && uv run mypy src tests && uv run pytest
```

Notes:

- Peak memory is measured in a subprocess per (cipher, size) so native allocations
  count; `--no-memory` skips it.
- Entropy and chi-square are sanity checks only; they carry no weight in the ranking.
- Mode comparison (`--mode-sizes`, default 16/64/256 MiB): one-shot (v1) vs chunked (v2)
  vs streaming AES-GCM (bench-only negative example). Inputs live on disk; only the
  one-shot mode needs ~2x the size in RAM, so 256 MiB is safe on any laptop.
- `src/bench/streaming_gcm.py` is deliberately not in the shared package: it releases
  plaintext before the tag is verified.
- Strip notebook outputs before committing: `uv run nbstripout notebooks/*.ipynb`.
