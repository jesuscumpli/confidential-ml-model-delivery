# confidential-crypto

Shared cryptographic core for the confidential model delivery PoC:

- `format`: versioned binary artifact format (header authenticated as AAD);
- `ciphers`: AEAD cipher implementations behind one protocol;
- `signers`: signature scheme implementations behind one protocol;
- `registry`: factory resolving algorithms by name or wire id;
- `keys`: key generation, loading and validation.

Contains no Hugging Face, Kubernetes or model-loading logic. Producer and
consumer depend on it as a uv path dependency. Algorithms needed only by the
evaluation phase are behind the `bench` extra.
