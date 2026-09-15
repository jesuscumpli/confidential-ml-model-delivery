"""Combines measurements and scorecard into one weighted ranking per category.

Weights are explicit inputs so the notebook can show how sensitive the decision is
to them. Every metric is min-max normalised to [0, 1] with 1 = best.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

CIPHER_WEIGHTS: Mapping[str, float] = {
    "encrypt_mib_s": 1.0,
    "decrypt_mib_s": 1.0,
    "peak_rss_mib": 0.5,
    "security_score": 3.0,
}

SIGNER_WEIGHTS: Mapping[str, float] = {
    "sign_ms": 0.5,
    "verify_ms": 1.0,
    "signature_bytes": 0.5,
    "security_score": 3.0,
}

_LOWER_IS_BETTER = {"peak_rss_mib", "sign_ms", "verify_ms", "keygen_ms", "signature_bytes"}


def _normalise(column: pd.Series[float]) -> pd.Series[float]:
    span = float(column.max() - column.min())
    if span == 0:
        return pd.Series(1.0, index=column.index)
    scaled: pd.Series[float] = (column - column.min()) / span
    return 1 - scaled if column.name in _LOWER_IS_BETTER else scaled


def rank(
    measurements: pd.DataFrame,
    scorecard: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    key: str,
) -> pd.DataFrame:
    """Return one row per algorithm with normalised columns and a weighted `total`."""
    aggregated = measurements.groupby(key).mean(numeric_only=True)
    aggregated["security_score"] = scorecard["score"].reindex(aggregated.index)
    table = pd.DataFrame(index=aggregated.index)
    for column, weight in weights.items():
        table[column] = _normalise(aggregated[column]) * weight
    table["total"] = table.sum(axis=1)
    table["production_safe"] = measurements.groupby(key)["production_safe"].first()
    return table.sort_values("total", ascending=False)
