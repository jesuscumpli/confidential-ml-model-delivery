"""Model artifact consumer: retrieve, verify and decrypt Hugging Face models.

Layer 1 decryption and Layer 2 signature verification are implemented in
this package. The consumer runs in Kubernetes and stores no secrets.
"""

__version__ = "0.1.0"
