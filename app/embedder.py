"""Local text embeddings for search by meaning (S-08, ADR-0013).

The model (``all-MiniLM-L6-v2``, ONNX) is downloaded once with ``make model``
and then loaded from disk; nothing is fetched at runtime (N-04).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

log = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
# SHA-256 of each file at MODEL_REVISION; ``make model`` refuses anything else.
MODEL_FILES: dict[str, str] = {
    "onnx/model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
}
DIMENSIONS = 384
MAX_TOKENS = 256
BATCH_SIZE = 32

Vectors = npt.NDArray[np.float32]


class Embedder(Protocol):
    """Turns texts into L2-normalized float32 vectors (one row per text)."""

    model_id: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> Vectors: ...


class ModelUnavailable(RuntimeError):
    """The model is not installed (or can't run on this computer); the reason is user-facing."""


def default_model_dir() -> Path:
    return Path.home() / ".cache" / "contacts-app" / "models" / MODEL_NAME


def normalize(vectors: Vectors) -> Vectors:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: Vectors = (vectors / norms).astype(np.float32)
    return out


class OnnxEmbedder:
    """Sentence-transformers style: token embeddings, mean-pooled over the attention mask."""

    def __init__(self, model_dir: Path) -> None:
        model_dir = model_dir.expanduser()
        missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
        if missing:
            raise ModelUnavailable(
                f"The search-by-meaning model is not installed in {model_dir}. "
                "Run `make model`, then restart the app."
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:  # e.g. no onnxruntime build for Intel Macs
            raise ModelUnavailable(
                "Search by meaning needs onnxruntime, which is not available on this computer."
            ) from exc
        from tokenizers import Tokenizer

        self.model_id = MODEL_NAME
        self.dimensions = DIMENSIONS
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")  # noqa: S106 - not a secret
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2  # stay polite on a laptop
        options.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(model_dir / "onnx/model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}

    def embed(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        parts = [
            self._embed_batch(texts[i : i + BATCH_SIZE]) for i in range(0, len(texts), BATCH_SIZE)
        ]
        return np.vstack(parts)

    def _embed_batch(self, texts: Sequence[str]) -> Vectors:
        encoded = self._tokenizer.encode_batch(list(texts))
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        tokens = np.asarray(self._session.run(None, feed)[0], dtype=np.float32)
        weights = mask[:, :, None].astype(np.float32)
        pooled = (tokens * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        return normalize(pooled.astype(np.float32))


def load_embedder(model_dir: Path) -> OnnxEmbedder:
    """Load the model from disk; raises ModelUnavailable with a user-facing reason."""
    embedder = OnnxEmbedder(model_dir)
    log.info("search-by-meaning model loaded from %s", model_dir)
    return embedder


def read_manifest(model_dir: Path) -> dict[str, object]:
    path = model_dir.expanduser() / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
