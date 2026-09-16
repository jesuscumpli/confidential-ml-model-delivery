# OpenDraw prompt — architecture diagram (Layer 1 + Layer 2)

Copy the block below into OpenDraw to generate a clean, visual architecture diagram
that summarizes what is implemented so far: **Layer 1** (AES-256-GCM chunked v2
encryption + key delivery via a Kubernetes Secret) and **Layer 2** (Ed25519 signing +
verify-before-decrypt).

```text
Generate a technical architecture diagram, clean and modern ("cloud architecture
diagram" style: light background, cards with soft shadows, flat icons, sans-serif
type), horizontal left-to-right layout, titled:

"Confidential ML Model Delivery — Layer 1 (encryption) + Layer 2 (signing)"

Draw 3 vertical zones separated by trust boundaries:

ZONE 1 — PRODUCER (trusted, offline)
A box titled "Producer (offline, trusted)" containing, in sequence:
1. "Model source: Hugging Face" -> model icon (bert-tiny / distilbert-base-uncased)
2. "Deterministic packaging" -> sorted tar + manifest.json with per-file SHA-256
3. "Layer 1 — Encrypt" -> AES-256-GCM, chunked mode (format v2), O(chunk) memory
4. "Layer 2 — Sign" -> Ed25519 with the private key
5. Output: two files "model.enc" and "model.sig"

ZONE 2 — HUGGING FACE HUB (untrusted)
Central box with a dashed red border and the label "Untrusted transport / storage".
Contains only the artifacts: "model.enc" + "model.sig". Never the plaintext model and
never the key. A large arrow goes from the Producer into this zone.

ZONE 3 — CONSUMER on KUBERNETES (kind cluster)
A box titled "Consumer — Kubernetes Job (kind)" with the numbered flow:
1. "Download model.enc + model.sig"
2. "Layer 2 — Verify signature (Ed25519, public key)"  <- MUST run before decrypt
3. "Layer 1 — Get key from Kubernetes Secret" (mounted as a read-only file)
4. "Decrypt (dispatch on version byte: v2 chunked)"
5. "Safe tar extraction (path-traversal guard)"
6. "Load model + tokenizer (Transformers)"
7. "Minimal inference (fill-mask) -> exit 0"

KEY SOURCES (on the right, feeding into the Consumer):
- "Kubernetes Secret" -> supplies the symmetric decryption key (Layer 1).
- "ConfigMap: public key" -> supplies the public verification key (Layer 2).
Trust anchor separate from the Hub: highlight this with a note.

SHARED COMPONENT:
A side box labeled "packages/confidential-crypto (shared)" touching both the Producer
and the Consumer, with the text "identical artifact format + registry on both sides
(format.py, ciphers/, signers/, registry.py)". Connect it with thin lines.

CONNECTIONS: use numbered arrows (1, 2, 3, ...) following execution order.
Color by layer consistently and add a legend:
- BLUE/TEAL = Layer 1 (confidentiality, symmetric encryption)
- PURPLE/ORANGE = Layer 2 (authenticity and integrity, asymmetric signature)
- GRAY = infrastructure / storage
- DASHED RED = trust boundary / untrusted zone

KEY ANNOTATIONS (small text next to the relevant arrows):
- "Verify BEFORE decrypt — enforced by the types (VerifiedArtifact)".
- "A compromised Hub cannot replace artifact + public key (anchor lives in the ConfigMap)".
- "Tamper demo: 1 altered byte in model.enc => verify fails => decrypt is never attempted".
- "Encryption = confidentiality; signature = authenticity/integrity. Different threats".

SHOW AT THE BOTTOM, as a lower band, the negative scenario:
"Tamper test: modify 1 byte of model.enc -> signature verification FAILS -> abort (no decrypt)".

VISUAL RULES:
- Understandable at a glance: maximum clarity, low noise, no source code.
- Use simple icons (padlock, key, signature, storage bucket, container, brain/model).
- Do NOT include Layer 3 (attestation / Confidential Containers): if desired, draw it as
  a dotted gray box labeled "Layer 3 — future / design only" with no active arrows.
- No real keys, tokens, or secret values anywhere in the diagram.
- Keep it on a single page, legible when printed on A4 landscape.

Deliver the diagram as an editable image/SVG, with labels in technical English.
```
