"""Producer failures, each mapped to a distinct process exit code.

Messages never contain key material or Hub tokens.
"""


class ProducerError(Exception):
    """Base class; `exit_code` is what the CLI returns when the error escapes."""

    exit_code = 1


class ConfigError(ProducerError):
    """Invalid settings, arguments or key file."""

    exit_code = 2


class PackagingError(ProducerError):
    """Model directory cannot be packaged deterministically."""

    exit_code = 3


class EncryptionError(ProducerError):
    """Cipher selection or encryption failed."""

    exit_code = 4


class HubError(ProducerError):
    """Hugging Face Hub download or upload failed."""

    exit_code = 5
