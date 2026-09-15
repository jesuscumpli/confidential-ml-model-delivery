"""Runners cover every registered algorithm and produce sane, complete rows."""

from __future__ import annotations

from confidential_crypto import registry

from bench import ciphers, signers


def test_cipher_runner_covers_all_available_ciphers() -> None:
    frame = ciphers.run([4096], repeats=1, measure_memory=False)
    expected = {c.name for c in registry.available_ciphers(include_unsafe=True)}
    assert set(frame["cipher"]) == expected
    assert frame["tamper_detected"].all()
    assert (frame["entropy_bits_per_byte"] > 7.9).all()
    assert (frame["overhead_bytes"] >= frame["tag_bytes"]).all()
    assert (frame["encrypt_mib_s"] > 0).all()


def test_signer_runner_covers_all_available_signers() -> None:
    frame = signers.run(1024, repeats=1)
    expected = {s.name for s in registry.available_signers(include_unsafe=True)}
    assert set(frame["scheme"]) == expected
    assert (frame["signature_bytes"] > 0).all()
    assert bool(frame.set_index("scheme").loc["ed25519", "deterministic"]) is True
