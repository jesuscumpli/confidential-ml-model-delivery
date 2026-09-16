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
- **Selected cipher: `aes-256-gcm`** (top of the weighted ranking; ranked #1).
- **Selected signer: `ed25519`** (top of the weighted ranking; ranked #1).
- **Selected encryption mode: chunked (format v2)** as the production default. Rationale:
  one-shot scored higher (18 vs 17) only on simplicity/format stability, but its memory
  grows with the artifact (~2x RAM) and LLM weights are multi-GB. Chunked keeps memory
  flat at O(chunk), matches one-shot's security guarantees, and showed no throughput
  penalty file-to-file. streaming-gcm was rejected (releases plaintext before auth).
  Producer/consumer code and the demo must default to chunked; one-shot stays available
  per artifact for small models. See `docs/crypto-evaluation.md` and (Spanish summary)
  `docs/crypto-decision.md`.

---

## M0 — Bootstrap adjustments

- [x] Commit `docs/plan.md`; add a short "Evaluation phase" section and the shared-package justification to it.
- [x] Create `packages/confidential-crypto` uv project (same ruff/mypy/pytest config as the services).
- [x] Create `benchmarks/` uv project (jupyter, pandas, matplotlib, `confidential-crypto[bench]`).
- [x] Wire workspace dependencies: producer, consumer and benchmarks depend on `confidential-crypto` as a workspace member.
- [x] Root `pyproject.toml` as a uv workspace (`packages/*`, `services/*`, `benchmarks`) with a single root `uv.lock` and shared dev tools; no per-member lockfiles.
- [x] Add notebook checkpoints and benchmark results to `.gitignore`; `nbstripout` in the benchmarks dev group.
- [x] `scripts/check.sh`: runs `ruff check`, `ruff format --check`, `mypy`, `pytest` across all workspace members.
- [x] Dockerfiles rebuilt with repository-root build context (workspace in context), each installing only its member's group (`uv sync --package`), non-root user.
- Acceptance: `uv sync --all-extras --all-groups --all-packages` and `scripts/check.sh` pass for the workspace.

## M1 — Artifact format + AES-256-GCM (baseline)

- [x] `format.py`: header `magic | version | cipher_id | nonce_len | nonce`, header bytes used as AAD.
- [x] `ciphers/base.py`: `AeadCipher` protocol (`cipher_id`, `name`, `key_size`, `nonce_size`, `encrypt`, `decrypt`).
- [x] `ciphers/aes_gcm.py` with random 96-bit nonce and key-length validation.
- [x] `registry.py`: factory by name and by id; unknown id fails explicitly.
- [x] `keys.py`: symmetric key generation, hex/raw loading, validation; guarantee no key bytes in exceptions/logs.
- [x] Tests: round-trip, wrong key, flipped ciphertext byte, flipped header byte (cipher_id swap must fail), truncated input, malformed magic/version, nonce uniqueness across calls.
- Acceptance: package tests green; `encrypt(decrypt(x)) == x` property test with random sizes (0 B, 1 B, 1 MiB).

## M2 — Additional ciphers and signers (for evaluation)

- [x] `ciphers/chacha20_poly1305.py`, `ciphers/aes_gcm_siv.py` (skip with clear error if OpenSSL lacks it).
- [x] Format v2 (chunked, STREAM construction): `encrypt_stream` / `decrypt_stream`, dispatch on version byte; negative tests for truncation, reordering, splicing, chunk-size tamper.
- [x] Zero-copy paths: `encrypt_parts` (no header concat), `memoryview` slice on decrypt, `Buffer` inputs.
- [x] `ciphers/xchacha20_poly1305.py` behind `[bench]` extra (PyNaCl).
- [x] `ciphers/aes_cbc_hmac.py` behind `[bench]`, flagged `production_safe = False` in the registry.
- [x] `signers/base.py`: `Signer`/`Verifier` protocols, signature envelope (`scheme_id | key_fingerprint | signature`).
- [x] `signers/ed25519.py`, `signers/ecdsa_p256.py`, `signers/rsa_pss.py`; `signers/ml_dsa.py` behind `[bench]` (skip if unavailable).
- [x] Shared parametrised test suite run against every registered cipher/signer (positive + negative paths).
- Acceptance: every algorithm passes the same conformance tests; the registry refuses non-production algorithms unless explicitly allowed.

## M3 — Crypto evaluation phase

- [x] `benchmarks/src/bench/`: runners for cipher throughput (1 MiB, 16 MiB, real artifact), peak memory, ciphertext overhead, entropy/byte-histogram, tamper check; signer keygen/sign/verify timing and sizes.
- [x] Mode benchmark (`modes.py`): one-shot vs chunked vs streaming-gcm (bench-only, v1 bytes, plaintext released before auth) file to file; peak RSS per operation in a fresh process via `VmHWM` (not `ru_maxrss`, which inherits the parent's RSS on Linux).
- [x] Qualitative security scorecard (`scorecard.yaml`): AEAD, nonce-misuse resistance, nonce collision bound, AES-NI dependency, standardisation (RFC/FIPS), library maturity, PQ resistance. Each row cites a source.
- [x] `benchmarks/notebooks/crypto_evaluation.ipynb`: tables + charts, one combined ranking per category.
- [x] `uv run bench export` writes `docs/crypto-evaluation.md` (ADR-style: context, candidates, measurements, decision, consequences).
- [x] Record the selected default cipher and signer in the registry (`DEFAULT_CIPHER = aes-256-gcm`, `DEFAULT_SIGNER = ed25519`).
- [x] Write `docs/crypto-decision.md` with plain-language rationale and the chunked-mode decision.
- Acceptance: notebook runs end to end from a clean `uv sync`; markdown export committed; decision defended with numbers; chunked mode justified for multi-GB LLM artifacts.

## M4 — Model packaging (producer)

- [x] `packaging.py`: download with `huggingface_hub.snapshot_download` (allow-list of files: config, tokenizer, weights), deterministic tar (sorted entries, mtime 0, uid/gid 0, no absolute paths).
- [x] Manifest inside the tar (`manifest.json`: model id, revision, file list + SHA-256).
- [x] Tests with a tiny fake model directory; reproducibility test (same input ⇒ same tar hash).
- Acceptance: tar restored with Transformers loads `bert-tiny` locally. Verified 2026-09-15
  (fill-mask top-1 for "The capital of France is [MASK]."). Note for M6: `bert-tiny` ships
  no `model_type` in `config.json` and no `tokenizer_config.json`, so with transformers 5.x
  the consumer must load with explicit `BertForMaskedLM` / `BertTokenizer` (the `Auto*`
  classes fail on the Hub copy too); `pytorch_model.bin` is its only weight file.

## M5 — Producer CLI + Hub publish + image

- [x] `producer` CLI (`argparse` or `typer`): `package`, `encrypt`, `publish`, `run` (all steps). Config via env: model id, revision, HF repo id, HF token, artifact name, key path/output, cipher name, encryption mode (**chunked default**, one-shot available per artifact).
- [x] Typed configuration object with `pydantic-settings` (env > defaults): the CLI reads into it; sensitive fields (e.g. HF token) are `SecretStr`; the decryption key is loaded from a user-given path — never an env var — and the settings object is never dumped/printed wholesale.
- [x] Key output: writes raw key to a path given by the user (never stdout by default), plus `scripts/gen-key.sh` (and the Secret is created from the key by `scripts/demo.sh`).
- [x] Hub client wrapper with an interface so integration tests can use a fake.
- [x] Dockerfile hardened: non-root, no cache, `uv sync --frozen --no-dev`.
- [x] Tests: CLI argument validation, publish uses fake client, plaintext never written to the upload dir.
- Acceptance: `model.enc` published to a test HF repo; repo contains only the encrypted artifact.
  Verified 2026-09-15 against `jesuscumpli/confidential-ml-model` (`.gitattributes` + `model.enc`).

## M6 — Consumer locally

- [x] `KeyProvider` abstraction: `FileKeyProvider` (mounted Secret), `EnvKeyProvider`; `CdhKeyProvider` stub documented for Layer 3.
- [x] Typed settings via `pydantic-settings` (env): model/repo/artifact names, secret mount path, public key path; sensitive fields as `SecretStr`; settings never dumped to logs and never contain key bytes (key stays inside `KeyProvider`).
- [x] Flow: download → (verify, M8) → decrypt (dispatch on version byte; **chunked v2 default**, one-shot v1 still supported) → safe tar extraction to temp dir (path traversal guard) → load with `AutoModelForMaskedLM` + tokenizer → fill-mask inference → print result.
- [x] Every failure maps to a distinct non-zero exit code; no secrets or key material in logs.
- [x] Tests: decrypt failures, unsafe tar members, model load with `bert-tiny` fixture (marked slow), exit codes, settings serialization (`model_dump`/`model_dump_json`) never contains key bytes or `SecretStr` values.
- [x] Dockerfile (non-root, CPU-only torch to keep the image small).
- Acceptance: `uv run consumer` locally completes inference on the published artifact.
  Verified 2026-09-15 (`france` top-1 from `jesuscumpli/confidential-ml-model`). Loader uses
  `Auto*` when `config.json` has `model_type`, explicit `Bert*` otherwise (bert-tiny).

## M7 — Layer 1 in Kubernetes (kind)

- [x] `scripts/kind-setup.sh` (cluster + build + load images), `scripts/kind-down.sh`.
- [x] `k8s/namespace.yaml`, `k8s/consumer-job.yaml` (Secret mounted as file, read-only FS, non-root, no service account token; Secret/ConfigMap generated at run time by `scripts/demo.sh`).
- [x] `scripts/demo.sh` (run): creates the Secret and ConfigMap from `HUB_REPO_ID`/`KEY_PATH`, applies the Job, waits, prints logs; `scripts/demo.sh negative [missing|corrupt]`: broken Secret ⇒ Job fails.
- Acceptance: fresh kind cluster completes inference; missing Secret gives a clear failure.
  Verified 2026-09-15: Job completes under the `restricted` Pod Security profile; corrupt
  Secret ⇒ `authentication failed`, exit 5; missing Secret ⇒ pod stuck on `FailedMount`.

## M8 — Layer 2 signing and verification

- [x] Producer: `sign` step using the selected signer (`gen-signing-keypair`, `sign`, `run` signs by default, `--no-sign` opt-out with a warning); `<artifact stem>.sig` (`model.sig` for `model.enc`) published next to the artifact in a single Hub commit, so one repo can hold several artifacts; `publish` refuses a missing/malformed signature; `scripts/gen-signing-keypair.sh`.
- [x] Crypto: `sign_stream`/`verify_stream` sign `"CMLS-v1-sha256\0" || SHA-256(artifact)` (hash-then-sign, domain-separated) so multi-GB artifacts are signed/verified with O(1) memory; `sign`/`verify` on bytes delegate to them.
- [x] Consumer: verification before any decryption, enforced by types (`decrypt_file` only accepts the `VerifiedArtifact` returned by `verify_file`; the Layer 1 key is not read before) and by `test_tampered_artifact_is_never_decrypted`; public key from the mounted ConfigMap (`CONSUMER_PUBLIC_KEY_PATH`); expected scheme from config, envelope scheme/fingerprint mismatch rejected; `--no-verify` development escape hatch logs a warning.
- [x] `k8s/configmap-public-key.yaml` generated by `scripts/gen-configmap-public-key.sh` (git-ignored); `k8s/consumer-job.yaml` mounts it read-only at `/etc/model-public-key/signing.pub` and reads `artifact_revision` from `consumer-config`.
- [x] `scripts/demo.sh negative tamper`: `scripts/publish-tampered.py` flips one byte of `model.enc` and pushes it with the original `model.sig` to the `tampered` branch of the same repo; the Job pinned to that revision fails with exit 4, no decryption attempted (real Secret in place).
- [x] Tests: valid verifies; modified artifact (header/body/tail), modified signature, wrong public key, scheme id mismatch, malformed envelope, missing signature, missing/non-PEM public key all fail with the expected exit code; producer refuses foreign-scheme and non-PEM signing keys.
- Acceptance: tamper demo reproducible from the README (README itself is M10). Verified
  locally 2026-09-16 with real `bert-tiny`: valid signature ⇒ `france` top-1; flipped
  byte ⇒ exit 4 `signature is invalid`; wrong public key ⇒ exit 4 `expected public key`.
  The kind run (`scripts/demo.sh` + `negative tamper`) is pending on the user's cluster.

## M9 — Integration tests + CI

- [ ] `tests/integration/`: full encrypt → sign → publish (fake Hub) → download → verify → decrypt → load with `bert-tiny`.
- [ ] Optional real-Hub test gated by `HF_TOKEN` env var.
- [ ] GitHub Actions: lint, type-check, unit tests for the three projects; integration test with fake Hub; kind smoke test (optional, manual trigger).
- Acceptance: CI green on `main`.

## M10 — Documentation

- [ ] `docs/architecture.md`: components, data flow, trust boundaries, deployment topology (Mermaid diagrams).
- [ ] `docs/security.md`: threat model, properties, assumptions, key lifecycle, failure modes, what L1/L2 do not protect, why the chosen cipher/signer and chunked mode (link to `docs/crypto-evaluation.md` and `docs/crypto-decision.md`), remaining risks.
- [ ] `docs/layers.md`: L1/L2 implementation, L3 design + feasibility (KVM requirement, CoCo operator, Trustee KBS, `CdhKeyProvider` design, permissive policy caveats).
- [ ] `README.md`: everything listed in `docs/plan.md` Section 7, followed end to end by a clean checkout.
- [ ] Tick every box in `docs/plan.md` Section 7.
- Acceptance: a reviewer can reproduce Layer 1 and the Layer 2 tamper demo from the README alone.
