"""Scorecard must cover every registered algorithm; export must render a full ADR."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from confidential_crypto import registry

from bench import export, ranking, scorecard


def test_scorecard_covers_registry() -> None:
    cipher_card, signer_card = scorecard.cipher_scorecard(), scorecard.signer_scorecard()
    assert set(cipher_card.index) == set(registry.CIPHERS)
    assert set(signer_card.index) == set(registry.SIGNERS)
    cipher_criteria, signer_criteria = scorecard.criteria()
    assert cipher_card[list(cipher_criteria)].isin([0, 1, 2, 3]).all().all()
    assert signer_card[list(signer_criteria)].isin([0, 1, 2, 3]).all().all()


def test_every_entry_cites_sources() -> None:
    cipher_notes, signer_notes = scorecard.notes()
    for entry in list(cipher_notes.values()) + list(signer_notes.values()):
        assert entry["sources"], "every scorecard entry needs at least one source"


def test_unsafe_cipher_scores_lowest() -> None:
    card = scorecard.cipher_scorecard()
    assert card["score"].idxmin() == "aes-256-cbc-hmac-sha256"


def _fake_cipher_results() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cipher": ["aes-256-gcm", "chacha20-poly1305"],
            "production_safe": [True, True],
            "size_bytes": [1 << 20, 1 << 20],
            "encrypt_mib_s": [1000.0, 1500.0],
            "decrypt_mib_s": [1100.0, 1600.0],
            "peak_rss_mib": [3.0, 3.0],
            "overhead_bytes": [35, 35],
            "key_bytes": [32, 32],
            "nonce_bytes": [12, 12],
            "tag_bytes": [16, 16],
            "entropy_bits_per_byte": [7.99, 7.99],
            "chi_square": [250.0, 260.0],
            "tamper_detected": [True, True],
        }
    )


def _fake_signer_results() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scheme": ["ed25519", "ecdsa-p256"],
            "production_safe": [True, True],
            "message_bytes": [1 << 20, 1 << 20],
            "keygen_ms": [0.05, 0.03],
            "sign_ms": [2.5, 0.6],
            "verify_ms": [1.3, 0.6],
            "public_key_pem_bytes": [113, 178],
            "signature_bytes": [64, 72],
            "deterministic": [True, False],
        }
    )


def _fake_mode_results() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mode": ["one-shot", "chunked", "streaming-gcm"],
            "cipher": ["aes-256-gcm"] * 3,
            "size_bytes": [64 << 20] * 3,
            "chunk_bytes": [1 << 20] * 3,
            "encrypt_mib_s": [500.0, 1000.0, 600.0],
            "decrypt_mib_s": [550.0, 900.0, 800.0],
            "peak_rss_encrypt_mib": [127.0, 2.5, 1.6],
            "peak_rss_decrypt_mib": [127.0, 3.4, 1.7],
            "overhead_bytes": [35, 1042, 35],
            "plaintext_released_before_auth": [False, False, True],
        }
    )


def test_mode_scorecard_covers_all_modes() -> None:
    from bench import modes

    card = scorecard.mode_scorecard()
    assert set(card.index) == set(modes.MODES)
    assert card.loc["streaming-gcm", "auth_before_release"] == 0
    assert card.loc["chunked", "memory_bound"] == 3


def test_ranking_orders_by_weighted_total() -> None:
    table = ranking.rank(
        _fake_cipher_results(),
        scorecard.cipher_scorecard(),
        {"encrypt_mib_s": 1.0, "security_score": 0.0},
        key="cipher",
    )
    assert list(table.index) == ["chacha20-poly1305", "aes-256-gcm"]
    assert table["total"].iloc[0] == 1.0


def test_export_writes_complete_document(tmp_path: Path) -> None:
    target = tmp_path / "eval.md"
    export.write(_fake_cipher_results(), _fake_signer_results(), _fake_mode_results(), target)
    text = target.read_text()
    for heading in (
        "## Context", "## Measurements", "### Encryption modes", "## Security scorecard",
        "## Decision", "### Encryption mode",
    ):  # fmt: skip
        assert heading in text
    assert registry.DEFAULT_CIPHER in text
    assert "Deviation" in text  # fake data ranks chacha20 above the default
