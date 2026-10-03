"""A deterministic stand-in for the real model: bag of hashed words (and word stems).

Texts that share words get similar vectors, which is enough to test indexing,
caching and ranking logic without the 90 MB model (ADR-0013).
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np

from app.embedder import Vectors, normalize

WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "on", "with", "who", "and", "to", "at", "in", "for", "is"}


class HashingEmbedder:
    model_id = "test-hashing"
    dimensions = 384

    def __init__(self) -> None:
        self.calls = 0
        self.texts = 0

    def embed(self, texts: Sequence[str]) -> Vectors:
        self.calls += 1
        self.texts += len(texts)
        out = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in WORD.findall(text.lower()):
                if word in STOP:
                    continue
                for token in {word, word[:5]}:
                    out[row, zlib.crc32(token.encode()) % self.dimensions] += 1.0
            out[row, 0] += 0.01  # never an all-zero vector
        return normalize(out)
