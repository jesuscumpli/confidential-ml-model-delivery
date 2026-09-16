"""Inference result types shared by the infrastructure and application layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Prediction:
    token: str
    probability: float


@dataclass(frozen=True, slots=True)
class LoadedModel:
    tokenizer: Any
    model: Any
