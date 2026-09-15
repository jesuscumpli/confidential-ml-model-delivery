"""Loads the qualitative scorecard shipped with the package as DataFrames."""

from __future__ import annotations

from importlib import resources
from typing import Any

import pandas as pd
import yaml


def _load() -> dict[str, Any]:
    text = resources.files("bench").joinpath("scorecard.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def _table(entries: dict[str, dict[str, Any]], criteria: dict[str, str]) -> pd.DataFrame:
    rows = [{"name": name, **{c: entry[c] for c in criteria}} for name, entry in entries.items()]
    frame = pd.DataFrame(rows).set_index("name")
    frame["score"] = frame[list(criteria)].sum(axis=1)
    return frame


def cipher_scorecard() -> pd.DataFrame:
    data = _load()
    return _table(data["ciphers"], data["cipher_criteria"])


def signer_scorecard() -> pd.DataFrame:
    data = _load()
    return _table(data["signers"], data["signer_criteria"])


def mode_scorecard() -> pd.DataFrame:
    data = _load()
    return _table(data["modes"], data["mode_criteria"])


def criteria() -> tuple[dict[str, str], dict[str, str]]:
    data = _load()
    return data["cipher_criteria"], data["signer_criteria"]


def mode_criteria() -> dict[str, str]:
    data: dict[str, str] = _load()["mode_criteria"]
    return data


def mode_notes() -> dict[str, dict[str, Any]]:
    data = _load()
    return {n: {"notes": e["notes"], "sources": e["sources"]} for n, e in data["modes"].items()}


def notes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Free-text notes and sources per algorithm, for the report."""
    data = _load()

    def pick(entries: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {n: {"notes": e["notes"], "sources": e["sources"]} for n, e in entries.items()}

    return pick(data["ciphers"]), pick(data["signers"])
