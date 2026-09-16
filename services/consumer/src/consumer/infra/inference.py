"""Load the restored model directory with Transformers and run one fill-mask prediction."""

from __future__ import annotations

import json
from pathlib import Path

from consumer.core.errors import InferenceError, ModelLoadError
from consumer.models.inference import LoadedModel, Prediction


def load_model(model_dir: Path) -> LoadedModel:
    """`Auto*` classes when `config.json` names its `model_type`; explicit BERT otherwise.

    Legacy checkpoints such as `prajjwal1/bert-tiny` predate the `model_type` key and
    ship only `vocab.txt`, which the `Auto*` resolvers cannot dispatch on.
    """
    try:
        config = json.loads((model_dir / "config.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise ModelLoadError(f"cannot read config.json from restored package: {exc}") from exc
    _quiet_transformers()
    try:
        if "model_type" in config:
            from transformers import AutoModelForMaskedLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(model_dir)
            model = AutoModelForMaskedLM.from_pretrained(model_dir)
        else:
            from transformers import BertForMaskedLM, BertTokenizer

            tokenizer = BertTokenizer.from_pretrained(model_dir)
            model = BertForMaskedLM.from_pretrained(model_dir)
    except Exception as exc:  # Transformers raises a wide range of loader exceptions
        raise ModelLoadError(f"cannot load model: {type(exc).__name__}: {exc}") from exc
    model.eval()
    return LoadedModel(tokenizer=tokenizer, model=model)


def _quiet_transformers() -> None:
    """Weight-loading reports and progress bars are noise in a Job log."""
    from transformers.utils import logging as hf_logging

    hf_logging.set_verbosity_error()  # type: ignore[no-untyped-call]
    hf_logging.disable_progress_bar()  # type: ignore[no-untyped-call]


def fill_mask(loaded: LoadedModel, prompt: str, top_k: int) -> list[Prediction]:
    import torch

    tokenizer, model = loaded.tokenizer, loaded.model
    encoded = tokenizer(prompt, return_tensors="pt")
    mask_positions = (encoded["input_ids"][0] == tokenizer.mask_token_id).nonzero()
    if len(mask_positions) != 1:
        raise InferenceError(f"prompt must contain exactly one {tokenizer.mask_token}")
    try:
        with torch.no_grad():
            logits = model(**encoded).logits[0, mask_positions[0, 0]]
    except Exception as exc:
        raise InferenceError(f"forward pass failed: {type(exc).__name__}") from exc
    probabilities = torch.softmax(logits, dim=-1)
    top = probabilities.topk(top_k)
    return [
        Prediction(token=tokenizer.decode([int(index)]).strip(), probability=float(prob))
        for prob, index in zip(top.values, top.indices, strict=True)
    ]
