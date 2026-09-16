"""Consumer failures, one distinct exit code per stage so a Job's status is diagnosable.

Messages never contain key material, tokens or plaintext model data.
"""


class ConsumerError(Exception):
    """Base class; `exit_code` is what the process returns when the error escapes."""

    exit_code = 1


class ConfigError(ConsumerError):
    """Invalid settings or an unusable key source."""

    exit_code = 2


class DownloadError(ConsumerError):
    """The artifact could not be fetched from the Hub."""

    exit_code = 3


class SignatureError(ConsumerError):
    """Layer 2 verification failed; nothing was decrypted."""

    exit_code = 4


class DecryptError(ConsumerError):
    """Layer 1 authentication failed: wrong key or tampered artifact."""

    exit_code = 5


class ExtractionError(ConsumerError):
    """The decrypted package is not a safe, well-formed model package."""

    exit_code = 6


class ModelLoadError(ConsumerError):
    """Transformers could not load the restored model directory."""

    exit_code = 7


class InferenceError(ConsumerError):
    """The forward pass failed or produced no usable prediction."""

    exit_code = 8
