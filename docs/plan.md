# Project Plan — Confidential ML Model Delivery

## 1. Objective

Implement a small, defensible proof-of-concept for confidential distribution of a Hugging Face ML model.

The system has two independent workloads:

```text
Producer
  │
  ├─ download small open model
  ├─ package model artifact
  ├─ encrypt artifact (AEAD cipher + mode from the evaluation; AES-256-GCM, chunked mode v2)
  ├─ sign encrypted artifact (Layer 2)
  └─ publish encrypted artifact + signature to Hugging Face Hub

                         ↓

                 Hugging Face Hub

                         ↓

Consumer (Kubernetes)
  │
  ├─ download encrypted artifact + signature
  ├─ obtain public verification material
  ├─ verify signature (Layer 2)
  ├─ obtain decryption key from Kubernetes Secret (Layer 1)
  ├─ decrypt artifact
  ├─ restore model files
  └─ load model + run a minimal inference
```

Layer 3 is optional and should not compromise the clarity or reliability of Layers 1 and 2.

---

## 2. Target architecture

### Repository

```text
confidential-ml-model-delivery/
├── packages/confidential-crypto/     # shared crypto package (format, registry, ciphers, signers)
│   ├── src/confidential_crypto/
│   ├── tests/
│   ├── pyproject.toml
│   └── uv.lock
├── services/producer/
│   ├── src/producer/
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── uv.lock
├── services/consumer/
│   ├── src/consumer/
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── uv.lock
├── benchmarks/                       # crypto evaluation: runners + Jupyter notebook
│   ├── src/bench/
│   ├── notebooks/
│   ├── pyproject.toml
│   └── uv.lock
├── k8s/
├── docs/
├── scripts/
├── tests/integration/
├── README.md
├── AGENTS.md
└── CLAUDE.md -> AGENTS.md
```

### Application boundaries

Producer and consumer are separate Python projects.

Reasons:
- independent dependency graphs;
- independent Docker images;
- independent deployment lifecycles;
- clear trust and responsibility boundaries;
- easier future evolution toward separate jobs/services.

Do not introduce a shared Python package unless duplication becomes substantial and has a clear justification.

The one justified exception is `packages/confidential-crypto`:
- the encrypted artifact format and the algorithm registry **must** be byte-for-byte identical on both sides; two copies would be a divergence risk, not a boundary;
- it contains no Hub, Kubernetes, or model-loading logic, so trust boundaries are unchanged;
- each service consumes it as a uv path dependency; extra algorithms used only in the evaluation live behind a `[bench]` optional extra, so producer and consumer images ship only `cryptography`.

### Crypto module design (modular, factory-based)

```text
confidential_crypto/
├── format.py      # header: magic | version | cipher_id | nonce_len | nonce ; header is AEAD AAD
├── ciphers/       # AeadCipher protocol + aes_gcm, chacha20_poly1305, aes_gcm_siv,
│                  #   xchacha20_poly1305 [bench], aes_cbc_hmac [bench, production_safe=False]
├── signers/       # Signer/Verifier protocols + ed25519, ecdsa_p256, rsa_pss, ml_dsa [bench]
├── registry.py    # factory: get_cipher(name) / cipher_from_id(id), get_signer(name); DEFAULT_*
└── keys.py        # key generation, loading, validation; no key material in errors/logs
```

Design rules:
- the header (including `cipher_id`) is authenticated as AAD, so an attacker cannot downgrade or swap the declared algorithm;
- the registry refuses algorithms flagged as not production-safe unless explicitly allowed (benchmarks only);
- the signature envelope carries `scheme_id | key_fingerprint | signature` so the consumer verifies with the intended scheme only;
- the consumer selects the decryptor from the header through the factory; the producer selects the cipher by name from configuration.

---

## 3. Scope and milestones

## Milestone 0 — Repository/bootstrap

Deliver:
- repository structure;
- `AGENTS.md` as the single source of agent instructions;
- `CLAUDE.md` symlink pointing to `AGENTS.md`;
- uv-based Python projects for producer and consumer;
- baseline lint/test configuration;
- `.gitignore` and `.dockerignore`.

Acceptance:
- `uv sync` works independently in producer and consumer;
- test suites start successfully;
- no secrets are present in Git.

## Milestone 1 — Model artifact definition

Choose one small Hugging Face model. The model ID is configurable; two are used:
- `prajjwal1/bert-tiny` (~17 MB) for unit/integration tests and CI;
- `distilbert-base-uncased` (~268 MB) for the demo and the throughput benchmarks.

Packaging is deterministic: sorted tar entries, mtime 0, uid/gid 0, no absolute paths,
plus a `manifest.json` with model id, revision and per-file SHA-256.
Two encryption modes share the header and registry: one-shot (format v1, whole
artifact in memory, ~2x RAM) and chunked (format v2, STREAM construction, O(chunk)
memory, each chunk authenticated before release). The evaluation phase compared them
and selected **chunked as the production default** (see Section 6): LLM artifacts weigh
GBs, so constant memory outweighs one-shot's simpler code. The producer selects the
mode per artifact and the consumer dispatches on the authenticated version byte.

Define a deterministic artifact format. Recommended approach:
1. download model repository files needed for local loading;
2. package them as a tar archive;
3. encrypt the resulting archive.

Document why the model was chosen and what files constitute the artifact.

Acceptance:
- a local plaintext model package can be created reproducibly;
- the consumer can later restore the exact directory expected by Transformers.

## Milestone 2 — Layer 1 encryption (shared crypto package)

Implement `packages/confidential-crypto` with AES-256-GCM as the baseline and the
factory/registry described in Section 2, then add the other candidate ciphers and
signers behind the same protocols.

Requirements:
- random nonce for each encryption operation;
- authenticated encryption (AEAD only for production algorithms);
- explicit binary format/versioning for the encrypted artifact, header authenticated as AAD;
- key length validation;
- tamper/decryption failure handling;
- no key material in logs;
- one parametrised conformance test suite executed against every registered algorithm.

Conceptual formats:

```text
v1 (one-shot):  magic | 1 | cipher_id | nonce_len | nonce            (header = AAD)
                ciphertext + tag

v2 (chunked):   magic | 2 | cipher_id | prefix_len | nonce_prefix | chunk_size
                chunk_0 | chunk_1 | ... | chunk_last
                nonce_i = prefix || counter || last_flag ; aad_i = header || counter || last_flag
```

Do not invent custom cryptography primitives; use mature libraries (`cryptography`,
`PyNaCl` for the libsodium comparison, `python-oqs`/`cryptography` for ML-DSA).

Tests:
- round-trip encryption/decryption;
- wrong key fails;
- modified ciphertext fails;
- modified header (including `cipher_id` swap) fails;
- malformed header/input fails;
- nonce handling is correct (unique per call, correct length);
- non-production algorithms are rejected by default;
- chunked: truncation at a chunk boundary, mid-chunk truncation, chunk reordering,
  chunk spliced from another artifact, chunk-size tamper, and no plaintext written
  before a failing chunk.

## Milestone 2b — Crypto evaluation phase

Compare the candidate algorithms with measurements before building the producer and
consumer on top of the chosen defaults. Lives in the separate `benchmarks/` uv project.

Candidates:
- ciphers: AES-256-GCM, ChaCha20-Poly1305, XChaCha20-Poly1305 (PyNaCl), AES-256-GCM-SIV,
  AES-CBC+HMAC (benchmark-only negative example, no native AEAD);
- signatures: Ed25519, ECDSA P-256, RSA-PSS 3072/4096, ML-DSA (post-quantum, if available);
- encryption modes: one-shot (v1), chunked (v2), and streaming AES-GCM with v1 bytes
  (benchmark-only negative example: releases plaintext before authentication).

Quantitative metrics:
- encrypt/decrypt throughput (MB/s) at 1 MiB, 16 MiB and the real model artifact;
- peak memory; ciphertext overhead; key and nonce sizes;
- Shannon entropy and byte-histogram uniformity of the ciphertext (sanity check only:
  every correct cipher scores ≈8 bits/byte; it detects implementation mistakes, it does
  not rank security);
- tamper check (one flipped byte must fail);
- signer keygen/sign/verify time, public key and signature sizes;
- per mode, file to file: throughput, peak RSS of encrypt and of decrypt (fresh process
  each, `VmHWM`), overhead, whether plaintext is released before authentication.

Qualitative scorecard (0–3, each row with a cited source):
- AEAD, nonce-misuse resistance, random-nonce collision bound;
- hardware acceleration dependency (AES-NI);
- standardisation (RFC/NIST/FIPS), library maturity;
- post-quantum resistance; determinism of signatures;
- modes: memory bound, authentication before release, truncation/reorder detection,
  cipher agnostic, format stability, implementation simplicity.

Deliverables:
- `benchmarks/notebooks/crypto_evaluation.ipynb` with tables and charts;
- `uv run bench export` writing `docs/crypto-evaluation.md` as an ADR (context, candidates,
  measurements, decision, consequences);
- `docs/crypto-decision.md`: plain-language summary of the decisions in Spanish;
- `DEFAULT_CIPHER` / `DEFAULT_SIGNER` recorded in the registry.

Acceptance:
- notebook runs end to end from a clean `uv sync`;
- the selected defaults are defended with numbers and cited properties;
- the chosen encryption mode (chunked) is justified for multi-GB LLM artifacts.

## Milestone 3 — Layer 1 producer

Producer flow:

```text
model source
  ↓
local package
  ↓
encrypt
  ↓
`model.enc`
  ↓
Hugging Face Hub
```

The producer should be runnable locally and in its Docker image.

Configuration should cover:
- Hugging Face repository ID;
- authentication token via environment/secret input;
- model ID;
- output artifact name;
- decryption key input/output mechanism;
- cipher and signer names (resolved through the registry; defaults from the evaluation).

The real decryption key must never be committed.

Acceptance:
- producer publishes an encrypted artifact successfully;
- repository contains only the encrypted artifact, never the plaintext model or raw key.

## Milestone 4 — Layer 1 Kubernetes consumer

Deploy a consumer workload using a Kubernetes Secret on a local `kind` cluster
(`scripts/kind-up.sh`, `scripts/build-images.sh`, `scripts/kind-load.sh`).

The consumer runs as a `Job` (one inference, then exit) so failures surface as a
non-zero exit code. Key retrieval goes through a `KeyProvider` abstraction
(`FileKeyProvider` for the mounted Secret, `EnvKeyProvider`; a `CdhKeyProvider` is
designed for Layer 3 but not implemented).

Recommended flow:

```text
Kubernetes Secret
      │
      └── mounted file / environment
                 ↓
           Consumer process
                 ↓
        download `model.enc`
                 ↓
             decrypt
                 ↓
          unpack to temp dir
                 ↓
      `AutoModel` / tokenizer load
                 ↓
        minimal inference
```

Requirements:
- manifest has no real secret value;
- secret is mounted only into consumer workload;
- consumer exits non-zero on verification/decryption/load failures;
- sensitive values are not printed.

Acceptance:
- fresh deployment can download, decrypt, load, and run inference;
- deleting or corrupting the Secret causes a clear failure.

## Milestone 5 — Layer 2 signing

Use an asymmetric signing scheme such as Ed25519 unless a documented alternative is preferable.

Producer:

```text
`model.enc`
   ↓
sign with private key
   ↓
`model.sig`
```

Publish the signature alongside the encrypted artifact.

Consumer:

```text
model.enc + model.sig
        ↓
verify with public key
        ↓
 valid? ── no → abort
   │
  yes
   ↓
decrypt
```

Tests:
- valid artifact verifies;
- changed artifact fails verification;
- changed signature fails verification;
- wrong public key fails verification;
- verification happens before decryption.

Important design point:
- the private signing key belongs only to the producer side;
- the consumer gets only the public verification key, delivered through a mounted
  ConfigMap (trust anchor separate from the Hub: a compromised Hub token cannot
  replace both artifact and public key);
- verification protects authenticity/integrity, not confidentiality;
- the signing scheme is selected through the registry; the default comes from the
  evaluation phase (Ed25519, see `docs/crypto-evaluation.md`).

## Milestone 6 — Kubernetes end-to-end verification

Create a repeatable demo path that proves:

### Layer 1
1. encrypted artifact exists in Hub;
2. Kubernetes consumer receives key through Secret;
3. consumer decrypts artifact;
4. consumer loads model;
5. inference succeeds.

### Layer 2
1. valid signature verifies;
2. deliberately modify one byte of the encrypted artifact;
3. verification fails;
4. consumer never attempts decryption/load.

The README should include exact commands and expected outcomes.

## Milestone 7 — Documentation polish

Required docs:

### `docs/architecture.md`
- component diagram;
- data flow;
- trust boundaries;
- deployment topology.

### `docs/security.md`
- threat model;
- security properties;
- assumptions;
- key lifecycle;
- failure modes;
- what Layer 1/2 do and do not protect;
- why AES-256-GCM and Ed25519 were selected;
- remaining risks.

### `docs/layers.md`
- Layer 1 implementation;
- Layer 2 implementation;
- Layer 3 design/implementation status.

### `README.md`
- project summary;
- prerequisites;
- repository layout;
- local development;
- image build;
- Hugging Face setup;
- key generation/setup;
- Kubernetes deployment;
- end-to-end verification;
- Layer 2 tamper demo;
- troubleshooting;
- optional Layer 3 notes.

---

## 4. Layer 3 — optional stretch goal

Decision (2026-09-15): Layer 3 is **designed and assessed in documentation only**, not
implemented. `docs/layers.md` covers the architecture, the `CdhKeyProvider` design,
the required manifests skeleton and the feasibility constraints (node with `/dev/kvm`,
so `kind` is not sufficient; CoCo operator; Trustee KBS; permissive policy caveats).

If it is ever implemented, only start after Layers 1 and 2 are complete, reproducible,
tested, and documented.

Goal:
- replace Kubernetes Secret delivery with attested key retrieval through Confidential Containers development mode;
- use `kata-qemu-coco-dev`;
- deploy CoCo operator and Trustee KBS;
- store key as a KBS resource;
- configure a permissive development policy for sample TEE attestation;
- configure consumer KBC/KBS connection through the required annotation;
- fetch resource through CDH at `127.0.0.1:8006`;
- verify end-to-end attestation and key release.

Success criterion:
- the consumer obtains the key from KBS via the attestation flow rather than a Kubernetes Secret.

Important:
- Layer 3 is infrastructure-heavy and environment-sensitive;
- keep it isolated in dedicated manifests/docs;
- do not make Layer 1/2 dependent on Layer 3.

---

## 5. Testing strategy

### Unit tests

`confidential-crypto`:
- artifact format and header authentication;
- parametrised conformance suite for every cipher and signer (positive + negative);
- registry behaviour (unknown ids, non-production algorithms).

Producer:
- encryption format;
- key validation;
- encryption/decryption;
- signing.

Consumer:
- parsing encrypted artifact;
- decryption;
- signature verification;
- failure paths;
- model loading with a tiny fixture/mock where practical.

### Integration tests

- publish/retrieve artifact against a controlled test repository or mocked Hub client;
- complete encrypt → sign → publish → download → verify → decrypt → load flow;
- Kubernetes smoke test where the environment permits it.

Security tests are first-class tests, not optional examples.

### CI

GitHub Actions runs `ruff check`, `ruff format --check`, `mypy` and `pytest` for the
three uv projects (`scripts/check.sh`), plus the integration test with a fake Hub
client and `bert-tiny`. The kind smoke test is a manual workflow.

---

## 6. Security decisions to defend in review

Be ready to explain:

### Why the selected cipher (AES-256-GCM)?
- efficient symmetric encryption for model artifacts;
- authenticated encryption;
- detects tampering during decryption;
- mature standard library support;
- measured against ChaCha20-Poly1305, XChaCha20-Poly1305, AES-GCM-SIV and CBC+HMAC in
  `docs/crypto-evaluation.md`; ranked #1 (4.8/5.0) in the weighted ranking.

### Why the selected signer (Ed25519)?
- compact signatures and keys;
- simple API;
- fast verification/signing;
- appropriate for artifact signing in a PoC;
- measured against ECDSA P-256, RSA-PSS and ML-DSA in `docs/crypto-evaluation.md`;
  ranked #1 (4.4/5.0) in the weighted ranking.

### Why a factory/registry instead of hardcoding one algorithm?
- makes the evaluation reproducible and the choice replaceable;
- the algorithm id is authenticated in the header, so agility does not open a downgrade path;
- the consumer never guesses: unknown or non-production ids abort.

### Why chunked mode over one-shot?
- one-shot was the top scorer (18 vs 17) but only on simplicity and format stability;
  its memory grows with the artifact (~2x RAM), which is not viable for multi-GB LLM weights;
- chunked keeps memory flat at O(chunk) for any artifact size, gives the same security
  guarantees (per-chunk authentication before release, truncation and reordering detection)
  and measured no speed penalty file-to-file (in practice faster, avoiding huge buffers);
- the consumer dispatches on the authenticated version byte, so one-shot remains available
  for small models on machines with spare RAM;
- streaming-gcm was rejected: it releases plaintext before authentication and only works
  with AES-GCM;
- full numbers and rationale in `docs/crypto-evaluation.md`; plain-language summary in
  `docs/crypto-decision.md`.

### Why a shared crypto package?
- see Section 2: format and registry must be identical on both sides; no Hub/K8s logic inside.

### Why separate producer and consumer projects?
- distinct workloads and dependency sets;
- clearer trust boundaries;
- independent images and deployment behavior.

### Why Kubernetes Secret for Layer 1?
- directly matches the assignment;
- simple operational mechanism for the baseline;
- clearly documented as a trust assumption.

### What remains unprotected?
- plaintext exists in consumer memory/filesystem after decryption;
- Kubernetes control plane/host remains inside the Layer 1 trust model;
- a compromised legitimate consumer can access plaintext;
- Hub credentials and signing private keys require secure handling outside this PoC.

### Why Layer 2 is separate from encryption?
- encryption gives confidentiality;
- signatures give authenticity/integrity;
- both address different threats.

---

## 7. Definition of done

The mandatory submission is considered complete when:

- [ ] Producer and consumer are separate uv projects.
- [ ] Both have independent Dockerfiles.
- [ ] Small Hugging Face model is selected and documented.
- [ ] Model artifact is encrypted with the AEAD cipher selected in the evaluation (AES-256-GCM) using chunked mode (format v2).
- [ ] Crypto evaluation notebook runs and `docs/crypto-evaluation.md` justifies the cipher and signer.
- [ ] Encryption mode decision (chunked) is documented and defensible.
- [ ] Encrypted artifact is published to Hugging Face Hub.
- [ ] Kubernetes Secret supplies the Layer 1 decryption key.
- [ ] Consumer downloads, decrypts, restores, and loads the model.
- [ ] Consumer performs a minimal successful inference.
- [ ] Layer 2 signs the encrypted artifact.
- [ ] Signature is published next to the artifact.
- [ ] Consumer verifies before decryption.
- [ ] Tamper test demonstrates verification failure.
- [ ] Unit tests cover positive and negative security paths.
- [ ] README can be followed by a fresh reviewer.
- [ ] Architecture and security decisions are documented and defensible.
- [ ] No secret material is committed.

Layer 3 may be incomplete or absent without making the mandatory submission incomplete.

---

## 8. Suggested implementation order for an agent

Do not jump directly to Layer 3.

Execute in this order:

1. Bootstrap repository and the three uv projects (`packages/confidential-crypto`, services, `benchmarks/`).
2. Implement and test the artifact format, AES-256-GCM and the registry.
3. Add the remaining candidate ciphers and signers under the same protocols and conformance tests.
4. Run the crypto evaluation phase; export `docs/crypto-evaluation.md`; fix registry defaults.
5. Implement and test deterministic artifact packaging.
6. Implement producer locally and publish to the Hub.
7. Implement consumer locally (`KeyProvider`, verify-before-decrypt structure).
8. Add kind scripts, Kubernetes Secret and consumer Job manifest; validate Layer 1 end-to-end.
9. Add signing/verification, ConfigMap public key; validate Layer 2 and the tamper scenario.
10. Integration tests and CI.
11. Finish documentation, including the Layer 3 design/feasibility write-up.

The detailed checklist per milestone lives in `docs/tasks.md`.
At each milestone, keep the system runnable. Avoid accumulating unverified infrastructure changes.
