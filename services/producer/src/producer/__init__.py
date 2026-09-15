"""Model artifact producer: package, encrypt and publish Hugging Face models.

Layer 1 encrypts the deterministic model package with the cipher selected in the
crypto evaluation (AES-256-GCM, chunked) and publishes only the encrypted artifact.
Layer 2 signing is added in a later milestone.
"""

__version__ = "0.1.0"
