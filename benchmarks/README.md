# benchmarks

Crypto evaluation phase (`docs/plan.md`, Milestone 2b). Measures the candidate
ciphers and signers from `confidential-crypto` and exports the decision record
to `docs/crypto-evaluation.md`.

```bash
uv sync
uv run bench --help          # runners and export (Milestone 2b)
uv run jupyter lab notebooks # interactive evaluation
```

Notebooks are stripped of outputs before commit (`nbstripout`).
