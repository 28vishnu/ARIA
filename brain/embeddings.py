"""
Lightweight local embedding engine for ARIA.

This version intentionally does NOT load a transformer model.

Why:
    ARIA currently runs on a memory-constrained Render instance.
    Loading sentence-transformers + PyTorch can consume enough RAM to
    stall or restart the entire service.

Instead we use a deterministic hashing-based embedding.

Properties:
    - 100% local
    - no API
    - no model download
    - no torch
    - very low RAM
    - deterministic
    - fixed 384-dimensional vectors
    - compatible with ChromaDB

This is an infrastructure-safe embedding layer.

A stronger ONNX/quantized embedding model can replace this implementation
later without changing the KnowledgeDatabase API.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import Iterable, List, Optional, Sequence


logger = logging.getLogger("aria")


# =========================================================
# Configuration
# =========================================================

DEFAULT_EMBEDDING_MODEL = "local-hash-384"

DEFAULT_DEVICE = "cpu"

DEFAULT_DIMENSION = 384

DEFAULT_BATCH_SIZE = 32

DEFAULT_MAX_LENGTH = 256


# =========================================================
# Runtime State
# =========================================================

_MODEL_NAME = os.getenv(
    "ARIA_EMBEDDING_MODEL",
    DEFAULT_EMBEDDING_MODEL,
)

_DEVICE = os.getenv(
    "ARIA_EMBEDDING_DEVICE",
    DEFAULT_DEVICE,
)

_DIMENSION = max(
    64,
    int(
        os.getenv(
            "ARIA_EMBEDDING_DIMENSION",
            str(DEFAULT_DIMENSION),
        )
    ),
)

_BATCH_SIZE = max(
    1,
    int(
        os.getenv(
            "ARIA_EMBEDDING_BATCH_SIZE",
            str(DEFAULT_BATCH_SIZE),
        )
    ),
)

_MAX_LENGTH = max(
    32,
    int(
        os.getenv(
            "ARIA_EMBEDDING_MAX_LENGTH",
            str(DEFAULT_MAX_LENGTH),
        )
    ),
)


# =========================================================
# Tokenization
# =========================================================

_TOKEN_PATTERN = re.compile(
    r"[a-zA-Z0-9_]+|[\u0080-\uFFFF]+"
)


def _normalize_text(text: str) -> str:
    """
    Normalize text before hashing.

    Keeps the operation deterministic while reducing irrelevant
    differences between equivalent inputs.
    """

    text = str(text or "")

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _tokenize(text: str) -> List[str]:
    """
    Lightweight tokenizer.

    No external NLP library is required.
    """

    text = _normalize_text(text)

    if not text:
        return []

    tokens = _TOKEN_PATTERN.findall(text)

    if len(tokens) > _MAX_LENGTH:
        tokens = tokens[:_MAX_LENGTH]

    return tokens


# =========================================================
# Stable Hashing
# =========================================================

def _stable_hash(value: str, seed: int = 0) -> int:
    """
    Produce a deterministic integer hash.

    Python's built-in hash() is intentionally randomized between
    processes, so it cannot be used for persistent embeddings.
    """

    payload = f"{seed}:{value}".encode(
        "utf-8",
        errors="ignore",
    )

    digest = hashlib.blake2b(
        payload,
        digest_size=8,
    ).digest()

    return int.from_bytes(
        digest,
        byteorder="little",
        signed=False,
    )


def _add_feature(
    vector: List[float],
    feature: str,
    weight: float,
) -> None:
    """
    Add a hashed feature to the vector.

    Two independent hashes are used:

        1. one determines the vector position
        2. one determines the sign

    This reduces systematic bias from feature collisions.
    """

    index_hash = _stable_hash(
        feature,
        seed=17,
    )

    sign_hash = _stable_hash(
        feature,
        seed=31,
    )

    index = index_hash % _DIMENSION

    sign = 1.0 if sign_hash % 2 == 0 else -1.0

    vector[index] += weight * sign


# =========================================================
# Single Text Embedding
# =========================================================

def _embed_text(text: str) -> List[float]:
    """
    Create a deterministic local vector.

    Features include:

        - individual tokens
        - adjacent token pairs
        - character n-grams

    This provides considerably better retrieval behavior than
    simply hashing the complete sentence.
    """

    normalized = _normalize_text(text)

    vector = [0.0] * _DIMENSION

    if not normalized:
        return vector

    tokens = _tokenize(normalized)

    if not tokens:
        return vector

    # -----------------------------------------------------
    # Word features
    # -----------------------------------------------------

    for token in tokens:

        # Main word feature
        _add_feature(
            vector,
            f"word:{token}",
            1.0,
        )

        # Prefix/suffix features help related word forms.
        if len(token) >= 4:

            _add_feature(
                vector,
                f"prefix:{token[:3]}",
                0.25,
            )

            _add_feature(
                vector,
                f"suffix:{token[-3:]}",
                0.25,
            )

    # -----------------------------------------------------
    # Bigram features
    # -----------------------------------------------------

    for index in range(
        len(tokens) - 1
    ):

        first = tokens[index]

        second = tokens[index + 1]

        _add_feature(
            vector,
            f"bigram:{first}|{second}",
            0.65,
        )

    # -----------------------------------------------------
    # Character n-gram features
    # -----------------------------------------------------

    compact = normalized.replace(
        " ",
        "_",
    )

    # Limit character processing so extremely large documents
    # cannot cause unnecessary CPU usage.
    compact = compact[:2048]

    for n in (3, 4):

        if len(compact) < n:
            continue

        for index in range(
            len(compact) - n + 1
        ):

            gram = compact[
                index:index + n
            ]

            _add_feature(
                vector,
                f"char{n}:{gram}",
                0.08,
            )

    # -----------------------------------------------------
    # L2 normalization
    # -----------------------------------------------------

    magnitude = math.sqrt(
        sum(
            value * value
            for value in vector
        )
    )

    if magnitude > 0.0:

        inverse = 1.0 / magnitude

        vector = [
            value * inverse
            for value in vector
        ]

    return vector


# =========================================================
# Public API
# =========================================================

def get_embedding(
    text: str,
) -> List[float]:
    """
    Generate one local embedding.

    This function intentionally never downloads or loads a model.
    """

    return _embed_text(
        str(text or "")
    )


def get_embeddings(
    texts: Sequence[str],
) -> List[List[float]]:
    """
    Generate embeddings for multiple texts.

    Kept as a batch-compatible API so KnowledgeDatabase does not
    need to know which embedding implementation is being used.
    """

    if not texts:
        return []

    return [
        get_embedding(text)
        for text in texts
    ]


def embedding_dimension() -> int:
    """
    Return the fixed embedding dimension.

    No model loading occurs.
    """

    return _DIMENSION


def embedding_model_name() -> str:
    """
    Return the active embedding implementation name.
    """

    return _MODEL_NAME


def embedding_available() -> bool:
    """
    Return whether local embeddings are available.

    Hash embeddings are always available unless the Python
    runtime itself is unavailable.
    """

    return True


def embedding_status() -> dict:
    """
    Return diagnostic information without loading anything.
    """

    return {
        "available": True,
        "model": _MODEL_NAME,
        "device": _DEVICE,
        "dimension": _DIMENSION,
        "batch_size": _BATCH_SIZE,
        "max_length": _MAX_LENGTH,
        "backend": "local_hash",
        "torch_required": False,
        "transformers_required": False,
    }


def clear_embedding_model_cache() -> None:
    """
    Compatibility function.

    The previous transformer implementation had a model cache.
    The lightweight implementation has no model to unload.
    """

    logger.info(
        "[Embeddings] No transformer model cache to clear."
    )


# =========================================================
# Compatibility Aliases
# =========================================================

def embed_text(
    text: str,
) -> List[float]:
    """
    Compatibility alias.
    """

    return get_embedding(text)


def embed_texts(
    texts: Sequence[str],
) -> List[List[float]]:
    """
    Compatibility alias.
    """

    return get_embeddings(texts)


def get_embedding_dimension() -> int:
    """
    Compatibility alias.
    """

    return embedding_dimension()


# =========================================================
# Startup Diagnostics
# =========================================================

logger.info(
    "[Embeddings] Lightweight local embedding engine ready | "
    "backend=local_hash | dimension=%d | device=%s | "
    "model=%s | torch_required=False",
    _DIMENSION,
    _DEVICE,
    _MODEL_NAME,
)