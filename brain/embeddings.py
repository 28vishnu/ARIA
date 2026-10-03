"""
ARIA Local Embedding Engine

This module provides local text embeddings for ARIA's knowledge system.

Design goals:
- No external embedding API required.
- Model is configurable through ARIA_EMBEDDING_MODEL.
- Model is loaded once and reused.
- Supports single and batch embeddings.
- Safe fallback when the local model is unavailable.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Iterable, List, Optional

logger = logging.getLogger("aria")


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DEFAULT_MODEL = os.getenv(
    "ARIA_EMBEDDING_MODEL",
    "BAAI/bge-m3",
)

EMBEDDING_DEVICE = os.getenv(
    "ARIA_EMBEDDING_DEVICE",
    "cpu",
)

NORMALIZE_EMBEDDINGS = os.getenv(
    "ARIA_NORMALIZE_EMBEDDINGS",
    "true",
).lower() not in {
    "0",
    "false",
    "no",
}


# ---------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_model():
    """
    Load the local embedding model exactly once.

    The model is intentionally lazy-loaded so ARIA startup does not
    download/load a multi-GB model unless embeddings are actually used.
    """

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        logger.error(
            "[Embeddings] sentence-transformers is not installed: %s",
            exc,
        )
        return None

    try:
        logger.info(
            "[Embeddings] Loading local model: %s | device=%s",
            DEFAULT_MODEL,
            EMBEDDING_DEVICE,
        )

        model = SentenceTransformer(
            DEFAULT_MODEL,
            device=EMBEDDING_DEVICE,
        )

        logger.info(
            "[Embeddings] Local embedding model loaded: %s",
            DEFAULT_MODEL,
        )

        return model

    except Exception as exc:
        logger.exception(
            "[Embeddings] Failed to load local model '%s': %s",
            DEFAULT_MODEL,
            exc,
        )
        return None


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def get_embedding(
    text: str,
) -> List[float]:
    """
    Generate one local embedding.

    Returns an empty list when the local model is unavailable.
    """

    if not text:
        return []

    text = str(text).strip()

    if not text:
        return []

    model = _load_model()

    if model is None:
        logger.warning(
            "[Embeddings] Local model unavailable; returning empty embedding."
        )
        return []

    try:
        vector = model.encode(
            text,
            normalize_embeddings=NORMALIZE_EMBEDDINGS,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return vector.tolist()

    except Exception as exc:
        logger.exception(
            "[Embeddings] Embedding generation failed: %s",
            exc,
        )
        return []


def get_embeddings(
    texts: Iterable[str],
    batch_size: int = 16,
) -> List[List[float]]:
    """
    Generate embeddings for multiple texts.

    Batch processing is important when ARIA ingests thousands or millions
    of knowledge chunks.
    """

    clean_texts = [
        str(text).strip()
        for text in texts
        if text is not None and str(text).strip()
    ]

    if not clean_texts:
        return []

    model = _load_model()

    if model is None:
        logger.warning(
            "[Embeddings] Local model unavailable; returning no embeddings."
        )
        return []

    try:
        vectors = model.encode(
            clean_texts,
            batch_size=batch_size,
            normalize_embeddings=NORMALIZE_EMBEDDINGS,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return vectors.tolist()

    except Exception as exc:
        logger.exception(
            "[Embeddings] Batch embedding generation failed: %s",
            exc,
        )
        return []


def embedding_dimension() -> Optional[int]:
    """
    Return the dimensionality of the currently configured model.
    """

    model = _load_model()

    if model is None:
        return None

    try:
        return int(model.get_sentence_embedding_dimension())
    except Exception:
        return None


def embedding_model_name() -> str:
    """Return the configured embedding model name."""

    return DEFAULT_MODEL


def embedding_available() -> bool:
    """Return whether the local embedding model can currently be loaded."""

    return _load_model() is not None


def clear_embedding_model_cache() -> None:
    """
    Clear the cached model.

    Useful for development/testing or switching models without restarting.
    """

    _load_model.cache_clear()

    logger.info(
        "[Embeddings] Local embedding model cache cleared."
    )