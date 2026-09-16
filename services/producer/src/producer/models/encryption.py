"""Encryption mode selected by the producer configuration."""

from enum import StrEnum


class EncryptionMode(StrEnum):
    """Chunked (format v2) is the production default; one-shot (v1) suits small models."""

    CHUNKED = "chunked"
    ONE_SHOT = "one-shot"
