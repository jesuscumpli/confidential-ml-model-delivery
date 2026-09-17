# Architecture

This document describes the system as it is built today: components, data flow,
trust boundaries and deployment topology. Every diagram is an SVG in `images/` with its
Mermaid source folded underneath; the same sources live in Mermaid Studio.

For the security layers in detail (what each one protects and how it is
implemented) see [`layers.md`](layers.md). For the algorithm choice see
[`crypto-evaluation.md`](crypto-evaluation.md).

## 1. Big picture

Two independent workloads. They never talk to each other. They only share the
Hugging Face Hub (untrusted storage) and two pieces of key material delivered
out of band.

![Big picture](images/arch-big-picture.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
    subgraph P["Producer (trusted, offline)"]
        direction TB
        P1["1. Download model<br/>(bert-tiny)"] --> P2["2. Package<br/>deterministic tar + manifest"]
        P2 --> P3["3. Encrypt — Layer 1<br/>AES-256-GCM, chunked v2"]
        P3 --> P4["4. Sign — Layer 2<br/>Ed25519 over SHA-256"]
    end

    subgraph H["Hugging Face Hub (untrusted)"]
        direction TB
        A["model.enc"]
        S["model.sig"]
    end

    subgraph C["Consumer — Kubernetes Job (trusted runtime)"]
        direction TB
        C1["1. Download<br/>model.enc + model.sig"] --> C2["2. Verify — Layer 2<br/>public key from ConfigMap"]
        C2 --> C3["3. Read key — Layer 1<br/>Secret mounted as file"]
        C3 --> C4["4. Decrypt<br/>dispatch on version byte"]
        C4 --> C5["5. Safe extract<br/>manifest hashes checked"]
        C5 --> C6["6. Load + fill-mask<br/>inference"]
    end

    subgraph KEYS["Out-of-band key material"]
        direction TB
        K1[("model.key<br/>→ Kubernetes Secret")]
        K2[("signing.pub<br/>→ ConfigMap")]
    end

    P -- "upload model.enc + model.sig<br/>(one commit)" --> H
    H -- "download" --> C
    KEYS -. "kubectl create secret / configmap" .-> C

    classDef untrusted fill:#fff3f3,stroke:#d33,color:#1b1b1b,stroke-dasharray: 5 5;
    class H untrusted;
```

</details>

Key facts:

- Only `model.enc` and `model.sig` ever reach the Hub. Never the plaintext model,
  never a key.
- The consumer verifies the signature **before** it reads the decryption key. A
  tampered artifact never touches Layer 1.
- Keys travel on a separate path: the symmetric key as a Kubernetes Secret, the
  public signing key as a ConfigMap. The Hub is not a trust anchor.

## 2. Components

![Components](images/arch-components.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart TB
    subgraph WS["uv workspace (one root pyproject.toml, one uv.lock)"]
        CC["packages/confidential-crypto<br/>format · registry · ciphers · signers · keys<br/><i>no Hub, no Kubernetes, no model code</i>"]
        PR["services/producer<br/>package → encrypt → sign → publish<br/>image: producer:dev"]
        CO["services/consumer<br/>download → verify → decrypt → restore → infer<br/>image: consumer:dev"]
        BE["benchmarks<br/>runners + notebook → docs/crypto-evaluation.md<br/><i>uses confidential-crypto[bench]</i>"]
    end
    IT["tests/integration<br/>both CLIs end to end, fake Hub"]
    K8S["k8s/ + scripts/<br/>namespace · Job · demo.sh · kind-setup.sh"]

    PR --> CC
    CO --> CC
    BE --> CC
    IT --> PR
    IT --> CO
    K8S --> CO
```

</details>

| Component | Responsibility | Ships in an image? |
|---|---|---|
| `confidential-crypto` | Encrypted artifact format (v1 one-shot, v2 chunked), signature envelope, algorithm registry, key loading. Identical bytes on both sides. | Yes, in both (without the `bench` extra) |
| `producer` | Downloads a Hub model, builds a deterministic tar, encrypts, signs, uploads. Reads keys from files the user names. | `producer:dev` |
| `consumer` | Fetches artifact + signature, verifies, decrypts, extracts safely, loads with Transformers, runs one fill-mask prompt. | `consumer:dev` (CPU-only torch) |
| `benchmarks` | Measures every candidate cipher, signer and mode; exports the decision record. | No |
| `tests/integration` | Full pipeline through the real CLIs with a fake Hub; synthetic 2-layer BERT by default, real `bert-tiny` under `-m slow`. | No |

### Internal layers of each service

Both services use the same layout. Dependencies point down only.

![Internal layers of each service](images/arch-service-layers.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart TB
    CLI["cli/<br/>typer commands, exit codes, printing"] --> APP["app/<br/>pipeline orchestration, step logging"]
    APP --> CORE["core/<br/>domain logic, errors, Protocol ports"]
    APP --> INFRA["infra/<br/>Hub client, key providers, Transformers"]
    INFRA --> CORE
    CORE --> MODELS["models/<br/>pydantic settings, manifest, plain data"]
    INFRA --> MODELS
```

</details>

Why it matters for security:

- `infra/keys.py` is the **only** code that touches key bytes. Settings hold paths,
  never keys.
- `core/ports.py` defines `KeyProvider` and `ArtifactSource` as `Protocol`s. Tests
  inject fakes; Layer 3 can add `CdhKeyProvider` without touching the pipeline.
- `cli/` maps every `ConsumerError` subclass to a distinct exit code, so a failed
  Job is diagnosable from `kubectl` alone.

## 3. Data flow

### Producer

![Producer data flow](images/arch-producer-flow.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
sequenceDiagram
    autonumber
    actor U as Operator
    participant P as producer CLI
    participant HF as Hugging Face Hub
    participant FS as var/ (git-ignored)

    U->>P: producer gen-key --out var/secrets/model.key
    U->>P: producer gen-signing-keypair --out var/secrets/signing.key
    U->>P: producer run --key-path ... --repo-id user/repo
    P->>HF: snapshot_download(model_id) — allow-listed files
    HF-->>P: config.json, tokenizer files, weights
    P->>FS: model.tar (sorted entries, mtime 0, manifest.json with SHA-256)
    P->>FS: upload/model.enc (AES-256-GCM chunked, header as AAD)
    P->>FS: upload/model.sig (Ed25519 over "CMLS-v1-sha256\0" ‖ SHA-256(model.enc))
    P->>HF: upload model.enc + model.sig in one commit
    HF-->>P: commit sha
    P-->>U: published model.enc + model.sig to user/repo at commit …
```

</details>

### Consumer

![Consumer data flow](images/arch-consumer-flow.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
sequenceDiagram
    autonumber
    participant K as Kubernetes
    participant C as consumer (Job pod)
    participant HF as Hugging Face Hub
    participant CM as ConfigMap model-public-key
    participant SE as Secret model-key

    K->>C: start with CONSUMER_* env, both volumes mounted read-only
    C->>HF: download model.enc @ revision
    C->>HF: download model.sig @ revision
    C->>CM: read /etc/model-public-key/signing.pub
    C->>C: verify envelope (scheme, fingerprint) + Ed25519 signature
    Note over C: exit 4 here on any mismatch — the key is never read
    C->>SE: read /etc/model-key/key (32 raw bytes)
    C->>C: decrypt chunk by chunk (v2) into private work dir
    Note over C: exit 5 on authentication failure (wrong key or tampered body)
    C->>C: safe tar extraction, manifest hashes verified
    C->>C: load model + tokenizer, fill-mask prompt
    C-->>K: table of top-k predictions, exit 0
```

</details>

### Artifact format (shared package)

```text
Encrypted artifact, version 2 (chunked, STREAM construction) — production default:

  "CMLD" | ver=2 | cipher_id | prefix_len | nonce_prefix | chunk_size u32 | chunk_0 … chunk_last

  chunk_i = AEAD(key, nonce_i, plaintext_i, aad_i)
  nonce_i = nonce_prefix ‖ counter_i (u32) ‖ last_flag (u8)
  aad_i   = header ‖ counter_i ‖ last_flag

Encrypted artifact, version 1 (one-shot) — still accepted for small models:

  "CMLD" | ver=1 | cipher_id | nonce_len | nonce | ciphertext+tag

Signature envelope (published as model.sig):

  "CMLS" | ver=1 | scheme_id | key_fingerprint (SHA-256 of public key PEM) | sig_len | signature
```

The header is always associated data. Flipping `cipher_id` or the version fails
authentication instead of selecting another algorithm. The consumer dispatches on
the authenticated version byte, so the producer can change mode per artifact.

## 4. Trust boundaries

![Trust boundaries](images/arch-trust-boundaries.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
    subgraph T1["Trusted: producer host"]
        PK[("signing.key<br/>private")]
        MK[("model.key<br/>symmetric")]
        PROD["producer"]
    end

    subgraph T0["Untrusted: network + Hub"]
        HUB["Hub repo<br/>model.enc, model.sig"]
    end

    subgraph T2["Trusted: Kubernetes cluster"]
        subgraph CP["Control plane / node"]
            SEC["Secret model-key"]
            CMAP["ConfigMap model-public-key"]
        end
        subgraph POD["Consumer pod (restricted PSS)"]
            CONS["consumer"]
            PT["plaintext model<br/>emptyDir, deleted on exit"]
        end
    end

    PROD --> HUB --> CONS
    MK -. out of band .-> SEC --> CONS
    PK -. public half, out of band .-> CMAP --> CONS
    CONS --> PT

    classDef untrusted fill:#fff3f3,stroke:#d33,color:#1b1b1b,stroke-dasharray: 5 5;
    class T0 untrusted;
```

</details>

| Boundary | What crosses it | Protection |
|---|---|---|
| Producer → Hub | `model.enc`, `model.sig` | Confidentiality by Layer 1; integrity + authenticity by Layer 2 |
| Hub → Consumer | same two files | Verified before use; any change ⇒ exit 4 |
| Operator → Cluster | `model.key` (Secret), `signing.pub` (ConfigMap) | Kubernetes RBAC; Secret mounted `0400`, read-only, no service-account token |
| Cluster → Pod | key file, public key file | Pod cannot escalate: non-root, `readOnlyRootFilesystem`, all capabilities dropped |

### Threat model in one table

| Threat | Layer 1 | Layer 2 | Layer 3 (design only) |
|---|---|---|---|
| Hub operator or network reads the model | Blocked (encrypted) | — | Blocked |
| Hub operator swaps or corrupts `model.enc` | Detected at decrypt (AEAD tag) | Detected before decrypt (signature) | Detected |
| Attacker publishes a different encrypted model with the same key | Not detected | **Blocked** (no private signing key) | Blocked |
| Attacker replaces `model.sig` with their own | — | Blocked (public key from ConfigMap, not from the Hub) | Blocked |
| Cluster admin reads the Secret | **Not protected** — trust assumption | — | Blocked (key released only after attestation) |
| Compromised consumer process | Not protected (plaintext in memory) | Not protected | Partially (TEE memory encryption) |
| Stolen Hub token | Attacker can upload; consumer rejects (Layer 2) | Blocked | Blocked |

Assumptions we state openly:

- The Kubernetes control plane, the node and the cluster operators are trusted for
  Layer 1 and Layer 2.
- The producer host keeps `model.key` and `signing.key` secret. Rotation is a
  re-run of the producer plus a new Secret/ConfigMap.
- Plaintext exists inside the pod after decryption. It lives in an `emptyDir` and a
  private `0700` temp directory that is removed on exit.

## 5. Deployment topology

![Deployment topology](images/arch-deployment-topology.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart TB
    subgraph HOST["Developer machine"]
        DOCKER["Docker<br/>producer:dev · consumer:dev"]
        SCRIPTS["scripts/<br/>kind-setup.sh · demo.sh · gen-*.sh"]
        VAR[("var/secrets/<br/>model.key · signing.key · signing.pub")]
        subgraph KIND["kind cluster: confidential-ml"]
            subgraph NS["namespace confidential-ml — PSS restricted"]
                JOB["Job consumer<br/>backoffLimit 0 · ttl 1h"]
                POD["Pod consumer<br/>uid 999 · read-only FS · no caps · seccomp RuntimeDefault"]
                SEC["Secret model-key<br/>→ /etc/model-key/key"]
                CM1["ConfigMap consumer-config<br/>hub_repo_id · artifact_name · artifact_revision"]
                CM2["ConfigMap model-public-key<br/>→ /etc/model-public-key/signing.pub"]
                ED["emptyDir /work, /tmp"]
            end
        end
    end
    HUB["Hugging Face Hub"]

    DOCKER -- "kind load docker-image" --> KIND
    SCRIPTS -- "kubectl apply" --> JOB
    VAR -- "create secret / configmap" --> SEC
    VAR --> CM2
    JOB --> POD
    SEC --> POD
    CM1 --> POD
    CM2 --> POD
    ED --> POD
    POD -- "HTTPS download" --> HUB
```

</details>

Runtime shape of the generated objects (nothing secret is committed; `demo.sh`
creates them on every run):

```yaml
# Secret (from var/secrets/model.key, 32 raw bytes)
apiVersion: v1
kind: Secret
metadata: { name: model-key, namespace: confidential-ml }
data: { key: <base64 of the key bytes> }
---
# ConfigMap: non-secret runtime configuration
apiVersion: v1
kind: ConfigMap
metadata: { name: consumer-config, namespace: confidential-ml }
data: { hub_repo_id: <user>/<repo>, artifact_name: model.enc, artifact_revision: main }
# optional keys: prompt, top_k (consumer defaults apply when absent)
---
# ConfigMap: Layer 2 trust anchor (rendered by scripts/gen-configmap-public-key.sh)
apiVersion: v1
kind: ConfigMap
metadata: { name: model-public-key, namespace: confidential-ml }
data: { signing.pub: "-----BEGIN PUBLIC KEY-----\n…" }
```

The producer image is built by `kind-setup.sh` but is not loaded into the cluster:
publishing runs on the operator's machine (or in CI), never inside the consumer
cluster.

## 6. Quality gates and CI

![Quality gates and CI](images/arch-quality-gates.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
    CHK["scripts/check.sh<br/>ruff · ruff format · mypy --strict · pytest<br/>per workspace member + tests/integration"]
    CI["ci.yml<br/>same gates, matrix per member"]
    DK["docker.yml<br/>build both images · non-root check<br/>Trivy image scan · Trivy IaC scan"]
    SEC["security.yml<br/>uv audit · gitleaks · Semgrep"]
    KS["kind-smoke.yml (manual)<br/>producer run → demo.sh run<br/>→ negative corrupt (exit 5)<br/>→ negative tamper (exit 4)"]
    CHK --> CI
    CI --> DK
    CI --> SEC
    DK --> KS
```

</details>

## 7. Design decisions (short form)

| Decision | Why |
|---|---|
| Separate producer / consumer projects | Different dependency graphs, images and trust roles. The consumer image never contains the Hub write path or the signing key logic. |
| One shared `confidential-crypto` package | The format and registry must be byte-identical on both sides. The package holds no Hub, Kubernetes or model code. |
| AES-256-GCM | Ranked #1 (4.8/5.0): fastest with AES-NI, standard, AEAD. One artifact per key keeps nonce risk trivial. |
| Ed25519 | Ranked #1 (4.4/5.0): deterministic, constant-time, 64-byte signatures, 32-byte keys. |
| Chunked mode (v2) as default | O(chunk) memory for multi-GB weights, same guarantees as one-shot, no measured throughput penalty. |
| Verify before decrypt, enforced by types | `decrypt_file` only accepts the `VerifiedArtifact` that `verify_file` returns. The mistake cannot compile. |
| Public key via ConfigMap, not the Hub | If the Hub could serve the trust anchor, Layer 2 would be circular. |
| Kubernetes Secret for the key | Exactly what the assignment asks; simple; a documented trust assumption that Layer 3 removes. |
| Registry with authenticated algorithm id | Agility without downgrade: the id is in the AAD, unknown or non-production ids abort. |
