# Task list — iterative delivery plan

Living checklist. Each milestone leaves the repository runnable, linted, typed,
tested and committed before the next one starts. Order follows `docs/plan.md`
Section 8 with one addition: a **crypto evaluation phase** (M3) that justifies
the algorithm choice with measurements before the producer/consumer are built
on top of it.

Decisions already taken (2026-09-15):

- Kubernetes: `kind` on the local machine; images loaded with `kind load`.
- Model: `prajjwal1/bert-tiny` for tests/CI, `distilbert-base-uncased` for the demo (model ID configurable).
- Layer 2 public key delivered through a mounted ConfigMap (trust anchor separate from the Hub).
- Layer 3: design + feasibility documented only, not implemented.
- Crypto code lives in a small shared package `packages/confidential-crypto` (format + registry must be identical on both sides).
- Evaluation lives in a separate uv project `benchmarks/` (Jupyter notebook + CLI script exporting `docs/crypto-evaluation.md`).
- Ciphers under evaluation: AES-256-GCM, ChaCha20-Poly1305, XChaCha20-Poly1305 (PyNaCl), AES-256-GCM-SIV, AES-CBC+HMAC (benchmark-only, marked insecure).
- Signatures under evaluation: Ed25519, ECDSA P-256, RSA-PSS 3072/4096, ML-DSA (if available).

---

## M0 — Bootstrap adjustments

- [x] Commit `docs/plan.md`; add a short "Evaluation phase" section and the shared-package justification to it.
- [x] Create `packages/confidential-crypto` uv project (same ruff/mypy/pytest config as the services).
- [x] Create `benchmarks/` uv project (jupyter, pandas, matplotlib, `confidential-crypto[bench]`).
- [x] Wire path dependencies: producer and consumer depend on `confidential-crypto`.
- [x] Add notebook checkpoints and benchmark results to `.gitignore`; `nbstripout` in the benchmarks dev group.
- [x] `scripts/check.sh`: runs `ruff check`, `ruff format --check`, `mypy`, `pytest` across all uv projects.
- [x] Dockerfiles rebuilt with repository-root build context (shared package in context), non-root user.
- Acceptance: `uv sync` and `scripts/check.sh` pass in all three projects.

## M1 — Artifact format + AES-256-GCM (baseline)

- [ ] `format.py`: header `magic | version | cipher_id | nonce_len | nonce`, header bytes used as AAD.
- [ ] `ciphers/base.py`: `AeadCipher` protocol (`cipher_id`, `name`, `key_size`, `nonce_size`, `encrypt`, `decrypt`).
- [ ] `ciphers/aes_gcm.py` with random 96-bit nonce and key-length validation.
- [ ] `registry.py`: factory by name and by id; unknown id fails explicitly.
- [ ] `keys.py`: symmetric key generation, hex/raw loading, validation; guarantee no key bytes in exceptions/logs.
- [ ] Tests: round-trip, wrong key, flipped ciphertext byte, flipped header byte (cipher_id swap must fail), truncated input, malformed magic/version, nonce uniqueness across calls.
- Acceptance: package tests green; `encrypt(decrypt(x)) == x` property test with random sizes (0 B, 1 B, 1 MiB).

## M2 — Additional ciphers and signers (for evaluation)

- [ ] `ciphers/chacha20_poly1305.py`, `ciphers/aes_gcm_siv.py` (skip with clear error if OpenSSL lacks it).
- [ ] `ciphers/xchacha20_poly1305.py` behind `[bench]` extra (PyNaCl).
- [ ] `ciphers/aes_cbc_hmac.py` behind `[bench]`, flagged `production_safe = False` in the registry.
- [ ] `signers/base.py`: `Signer`/`Verifier` protocols, signature envelope (`scheme_id | key_fingerprint | signature`).
- [ ] `signers/ed25519.py`, `signers/ecdsa_p256.py`, `signers/rsa_pss.py`; `signers/ml_dsa.py` behind `[bench]` (skip if unavailable).
- [ ] Shared parametrised test suite run against every registered cipher/signer (positive + negative paths).
- Acceptance: every algorithm passes the same conformance tests; the registry refuses non-production algorithms unless explicitly allowed.

## M3 — Crypto evaluation phase

- [ ] `benchmarks/src/bench/`: runners for cipher throughput (1 MiB, 16 MiB, real artifact), peak memory, ciphertext overhead, entropy/byte-histogram, tamper check; signer keygen/sign/verify timing and sizes.
- [ ] Qualitative security scorecard (`scorecard.yaml`): AEAD, nonce-misuse resistance, nonce collision bound, AES-NI dependency, standardisation (RFC/FIPS), library maturity, PQ resistance. Each row cites a source.
- [ ] `benchmarks/notebooks/crypto_evaluation.ipynb`: tables + charts, one combined ranking per category.
- [ ] `uv run bench export` writes `docs/crypto-evaluation.md` (ADR-style: context, candidates, measurements, decision, consequences).
- [ ] Record the selected default cipher and signer in the registry (`DEFAULT_CIPHER`, `DEFAULT_SIGNER`).
- Acceptance: notebook runs end to end from a clean `uv sync`; markdown export committed; decision defended with numbers.

## M4 — Model packaging (producer)

- [ ] `packaging.py`: download with `huggingface_hub.snapshot_download` (allow-list of files: config, tokenizer, weights), deterministic tar (sorted entries, mtime 0, uid/gid 0, no absolute paths).
- [ ] Manifest inside the tar (`manifest.json`: model id, revision, file list + SHA-256).
- [ ] Tests with a tiny fake model directory; reproducibility test (same input ⇒ same tar hash).
- Acceptance: tar restored with Transformers loads `bert-tiny` locally.

## M5 — Producer CLI + Hub publish + image

- [ ] `producer` CLI (`argparse` or `typer`): `package`, `encrypt`, `publish`, `run` (all steps). Config via env/flags: model id, revision, HF repo id, HF token, artifact name, key path/output, cipher name.
- [ ] Key output: writes raw key to a path given by the user (never stdout by default), plus `scripts/gen-key.sh` and `scripts/create-k8s-secret.sh`.
- [ ] Hub client wrapper with an interface so integration tests can use a fake.
- [ ] Dockerfile hardened: non-root, no cache, `uv sync --frozen --no-dev`.
- [ ] Tests: CLI argument validation, publish uses fake client, plaintext never written to the upload dir.
- Acceptance: `model.enc` published to a test HF repo; repo contains only the encrypted artifact.

## M6 — Consumer locally

- [ ] `KeyProvider` abstraction: `FileKeyProvider` (mounted Secret), `EnvKeyProvider`; `CdhKeyProvider` stub documented for Layer 3.
- [ ] Flow: download → (verify, M8) → decrypt → safe tar extraction to temp dir (path traversal guard) → load with `AutoModelForMaskedLM` + tokenizer → fill-mask inference → print result.
- [ ] Every failure maps to a distinct non-zero exit code; no secrets or key material in logs.
- [ ] Tests: decrypt failures, unsafe tar members, model load with `bert-tiny` fixture (marked slow), exit codes.
- [ ] Dockerfile (non-root, CPU-only torch to keep the image small).
- Acceptance: `uv run consumer` locally completes inference on the published artifact.

## M7 — Layer 1 in Kubernetes (kind)

- [ ] `scripts/kind-up.sh` / `kind-down.sh`, `scripts/build-images.sh`, `scripts/kind-load.sh`.
- [ ] `k8s/namespace.yaml`, `k8s/secret.example.yaml` (placeholder only), `k8s/consumer-job.yaml` (Secret mounted as file, read-only FS, non-root, no service account token).
- [ ] `scripts/demo-layer1.sh`: create Secret from key file, apply Job, wait, print logs; `scripts/demo-layer1-negative.sh`: delete/corrupt Secret ⇒ Job fails.
- Acceptance: fresh kind cluster completes inference; missing Secret gives a clear failure.

## M8 — Layer 2 signing and verification

- [ ] Producer: `sign` step using the selected signer; `model.sig` published next to `model.enc`; `scripts/gen-signing-keypair.sh`.
- [ ] Consumer: verification before any decryption (enforced by code structure and a test asserting decrypt is not called on failure); public key from mounted ConfigMap.
- [ ] `k8s/configmap-public-key.yaml` generated by script (public key is not a secret but is not committed either, to keep the demo reproducible).
- [ ] `scripts/demo-layer2-tamper.sh`: flip one byte of `model.enc` (local copy or separate HF repo/revision), run consumer ⇒ verification fails, no decryption attempted.
- [ ] Tests: valid verifies; modified artifact, modified signature, wrong key all fail; scheme id mismatch fails.
- Acceptance: tamper demo reproducible from the README.

## M9 — Integration tests + CI

- [ ] `tests/integration/`: full encrypt → sign → publish (fake Hub) → download → verify → decrypt → load with `bert-tiny`.
- [ ] Optional real-Hub test gated by `HF_TOKEN` env var.
- [ ] GitHub Actions: lint, type-check, unit tests for the three projects; integration test with fake Hub; kind smoke test (optional, manual trigger).
- Acceptance: CI green on `main`.

## M10 — Documentation

- [ ] `docs/architecture.md`: components, data flow, trust boundaries, deployment topology (Mermaid diagrams).
- [ ] `docs/security.md`: threat model, properties, assumptions, key lifecycle, failure modes, what L1/L2 do not protect, why the chosen cipher/signer (link to `docs/crypto-evaluation.md`), remaining risks.
- [ ] `docs/layers.md`: L1/L2 implementation, L3 design + feasibility (KVM requirement, CoCo operator, Trustee KBS, `CdhKeyProvider` design, permissive policy caveats).
- [ ] `README.md`: everything listed in `docs/plan.md` Section 7, followed end to end by a clean checkout.
- [ ] Tick every box in `docs/plan.md` Section 7.
- Acceptance: a reviewer can reproduce Layer 1 and the Layer 2 tamper demo from the README alone.
