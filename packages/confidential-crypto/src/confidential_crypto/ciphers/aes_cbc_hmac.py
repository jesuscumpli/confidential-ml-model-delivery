"""AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC). Evaluation only.

Included as the negative example: a hand-rolled AEAD composition. It is marked
`production_safe = False` because the security depends on getting the composition
right (MAC over nonce, aad and ciphertext; constant-time comparison; separate keys)
instead of on a single reviewed primitive.
"""

from __future__ import annotations

import hmac

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from confidential_crypto.ciphers.base import check_key, check_nonce
from confidential_crypto.errors import DecryptionError


class AesCbcHmacSha256:
    cipher_id = 0x7F
    name = "aes-256-cbc-hmac-sha256"
    key_size = 32
    nonce_size = 16
    tag_size = 32
    production_safe = False

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _subkeys(key: bytes) -> tuple[bytes, bytes]:
        derived = HKDF(
            algorithm=hashes.SHA256(), length=64, salt=None, info=b"cbc-hmac-subkeys"
        ).derive(key)
        return derived[:32], derived[32:]

    @staticmethod
    def _mac(mac_key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
        aad_len = len(aad).to_bytes(8, "big")
        return hmac.new(mac_key, aad_len + aad + nonce + ciphertext, "sha256").digest()

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        enc_key, mac_key = self._subkeys(key)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(enc_key), modes.CBC(nonce)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return ciphertext + self._mac(mac_key, nonce, aad, ciphertext)

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        check_key(self, key)
        check_nonce(self, nonce)
        if len(ciphertext) < self.tag_size + 16:
            raise DecryptionError(f"{self.name}: authentication failed")
        enc_key, mac_key = self._subkeys(key)
        body, tag = ciphertext[: -self.tag_size], ciphertext[-self.tag_size :]
        if not hmac.compare_digest(tag, self._mac(mac_key, nonce, aad, body)):
            raise DecryptionError(f"{self.name}: authentication failed")
        decryptor = Cipher(algorithms.AES(enc_key), modes.CBC(nonce)).decryptor()
        padded = decryptor.update(body) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        try:
            return unpadder.update(padded) + unpadder.finalize()
        except ValueError as exc:
            raise DecryptionError(f"{self.name}: authentication failed") from exc


AES_256_CBC_HMAC_SHA256 = AesCbcHmacSha256()
