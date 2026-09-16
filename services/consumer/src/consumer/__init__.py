"""Model artifact consumer: retrieve, verify, decrypt, restore and run one inference.

The consumer runs as a Kubernetes Job. The Layer 1 key reaches it only through a
`KeyProvider` (a mounted Secret file by default); it never lives in settings or logs.
"""

__version__ = "0.1.0"
