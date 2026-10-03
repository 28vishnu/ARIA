"""
ARIA Local Embedding Engine

Purpose
-------
Provides local semantic embeddings without requiring an external
embedding API.

Render / low-memory design
--------------------------
The default model is intentionally lightweight:

    sentence-transformers/all-MiniLM-L6-v2

This is substantially smaller than BAAI/bge-m3 and is much more
appropriate for low-memory CPU deployments.

The model is loaded lazily. Importing this module does NOT load
Torch or the embedding model into memory.

Configuration
-------------
ARIA_EMBEDDING_MODEL
    Override the model name.

ARIA_EMBEDDING_DEVICE
    cpu / cuda / auto

ARIA_EMBEDDING_BATCH_SIZE
    Batch size used during embedding generation.

ARIA_EMBEDDING_MAX_LENGTH
    Maximum tokenizer sequence length.

Examples
--------
Local development:

    ARIA_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

Higher-memory server:

    ARIA_EMBEDDING_MODEL=BAAI/bge-m3

Important
---------
The selected model's embedding dimension must match the Chroma
collection created for that model.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Iterable, List, Optional, Sequence

logger = logging.getLogger("aria")


# =========================================================
# DEFAULT CONFIGURATION
# =========================================================
#
# BGE-M3 is excellent but too memory-heavy for a small Render
# instance when combined with:
#
#   - FastAPI
#   - Torch
#   - ChromaDB
#   - MongoDB driver
#   - ARIA subsystems
#
# MiniLM is intentionally the default for deployment safety.
# =========================================================

DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/all-MiniLM-L6-v2"
)

DEFAULT_DEVICE = "cpu"

DEFAULT_BATCH_SIZE = 8

DEFAULT_MAX_LENGTH = 256


# =========================================================
# GLOBAL MODEL STATE
# =========================================================

_embedding_model = None

_embedding_model_name: Optional[str] = None

_embedding_dimension: Optional[int] = None

_embedding_device: Optional[str] = None

_embedding_failed = False

_embedding_lock = threading.Lock()


# =========================================================
# CONFIGURATION HELPERS
# =========================================================

def embedding_model_name() -> str:
    """
    Return the configured local embedding model name.

    The environment variable is evaluated dynamically so deployment
    configuration can override the default without changing code.
    """

    return str(
        os.getenv(
            "ARIA_EMBEDDING_MODEL",
            DEFAULT_EMBEDDING_MODEL,
        )
    ).strip() or DEFAULT_EMBEDDING_MODEL


def embedding_device() -> str:
    """
    Return the configured embedding device.

    Supported values:

        cpu
        cuda
        auto

    For Render deployments, CPU is the safe default.
    """

    configured = str(
        os.getenv(
            "ARIA_EMBEDDING_DEVICE",
            DEFAULT_DEVICE,
        )
    ).strip().lower()

    if configured not in {
        "cpu",
        "cuda",
        "auto",
    }:
        logger.warning(
            "[Embeddings] Invalid ARIA_EMBEDDING_DEVICE=%s; "
            "falling back to cpu.",
            configured,
        )

        return DEFAULT_DEVICE

    return configured


def embedding_batch_size() -> int:
    """
    Return the embedding batch size.

    A small batch is intentionally used to reduce peak RAM usage.
    """

    raw = os.getenv(
        "ARIA_EMBEDDING_BATCH_SIZE",
        str(DEFAULT_BATCH_SIZE),
    )

    try:
        value = int(raw)

    except (
        TypeError,
        ValueError,
    ):
        value = DEFAULT_BATCH_SIZE

    return max(
        1,
        min(
            value,
            32,
        ),
    )


def embedding_max_length() -> int:
    """
    Return the maximum tokenizer sequence length.

    Lowering this reduces memory usage for large documents.
    """

    raw = os.getenv(
        "ARIA_EMBEDDING_MAX_LENGTH",
        str(DEFAULT_MAX_LENGTH),
    )

    try:
        value = int(raw)

    except (
        TypeError,
        ValueError,
    ):
        value = DEFAULT_MAX_LENGTH

    return max(
        32,
        min(
            value,
            512,
        ),
    )


# =========================================================
# DEVICE RESOLUTION
# =========================================================

def _resolve_device() -> str:
    """
    Resolve the actual device used by SentenceTransformer.
    """

    configured = embedding_device()

    if configured == "cpu":
        return "cpu"

    if configured == "cuda":

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"

            logger.warning(
                "[Embeddings] CUDA requested but unavailable; "
                "falling back to CPU."
            )

        except Exception:
            logger.exception(
                "[Embeddings] Failed to inspect CUDA availability."
            )

        return "cpu"

    # auto
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"

    except Exception:
        logger.exception(
            "[Embeddings] Failed to detect CUDA."
        )

    return "cpu"


# =========================================================
# MODEL LOADING
# =========================================================

def _load_embedding_model():
    """
    Lazily load the SentenceTransformer model.

    The model is NOT loaded during module import.

    This is important for Render because ARIA should boot even when
    local embedding resources are unavailable or insufficient.
    """

    global _embedding_model
    global _embedding_model_name
    global _embedding_dimension
    global _embedding_device
    global _embedding_failed

    if _embedding_model is not None:
        return _embedding_model

    if _embedding_failed:
        return None

    with _embedding_lock:

        if _embedding_model is not None:
            return _embedding_model

        if _embedding_failed:
            return None

        model_name = embedding_model_name()
        device = _resolve_device()

        try:

            logger.info(
                "[Embeddings] Loading local embedding model: %s | device=%s",
                model_name,
                device,
            )

            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                model_name,
                device=device,
            )

            # Keep tokenizer sequence length bounded.
            #
            # This reduces memory consumption for large documents
            # without affecting normal short factual questions.
            try:
                model.max_seq_length = embedding_max_length()

            except Exception:
                logger.debug(
                    "[Embeddings] Could not set max_seq_length.",
                    exc_info=True,
                )

            dimension = int(
                model.get_sentence_embedding_dimension()
            )

            _embedding_model = model
            _embedding_model_name = model_name
            _embedding_dimension = dimension
            _embedding_device = device

            logger.info(
                "[Embeddings] Local embedding model ready | "
                "model=%s | dimension=%d | device=%s | "
                "batch_size=%d | max_length=%d",
                model_name,
                dimension,
                device,
                embedding_batch_size(),
                embedding_max_length(),
            )

            return _embedding_model

        except Exception as exc:

            _embedding_failed = True

            logger.exception(
                "[Embeddings] Failed to load local embedding model "
                "%s: %s",
                model_name,
                exc,
            )

            return None


# =========================================================
# PUBLIC MODEL ACCESS
# =========================================================

def get_embedding_model():
    """
    Return the lazily-loaded local SentenceTransformer model.

    Returns:
        SentenceTransformer instance or None.
    """

    return _load_embedding_model()


# =========================================================
# SINGLE EMBEDDING
# =========================================================

def get_embedding(
    text: str,
) -> List[float]:
    """
    Generate one local embedding.

    Never raises an embedding-model exception to the caller.

    Returns:
        List[float] containing the embedding, or [] when the
        local embedding engine is unavailable.
    """

    if text is None:
        return []

    cleaned = str(
        text
    ).strip()

    if not cleaned:
        return []

    model = _load_embedding_model()

    if model is None:
        return []

    try:

        embedding = model.encode(
            cleaned,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return embedding.astype(
            "float32"
        ).tolist()

    except Exception:

        logger.exception(
            "[Embeddings] Single embedding generation failed."
        )

        return []


# =========================================================
# BATCH EMBEDDINGS
# =========================================================

def get_embeddings(
    texts: Sequence[str],
) -> List[List[float]]:
    """
    Generate local embeddings for multiple texts.

    Uses a deliberately small batch size to reduce peak RAM.

    Empty input returns [].

    Invalid/empty individual texts are represented by [] so callers
    can preserve positional alignment when necessary.
    """

    if not texts:
        return []

    normalized_texts = [
        str(text or "").strip()
        for text in texts
    ]

    if not any(
        normalized_texts
    ):
        return [
            []
            for _ in normalized_texts
        ]

    model = _load_embedding_model()

    if model is None:

        return [
            []
            for _ in normalized_texts
        ]

    try:

        batch_size = embedding_batch_size()

        embeddings = model.encode(
            normalized_texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return [
            vector.astype(
                "float32"
            ).tolist()
            for vector in embeddings
        ]

    except Exception:

        logger.exception(
            "[Embeddings] Batch embedding generation failed."
        )

        return [
            []
            for _ in normalized_texts
        ]


# =========================================================
# ITERABLE EMBEDDINGS
# =========================================================

def get_embeddings_iterable(
    texts: Iterable[str],
) -> List[List[float]]:
    """
    Convenience wrapper for generators/iterables.

    The iterable is materialized once and passed through the same
    safe batch path.
    """

    try:

        values = list(
            texts
        )

    except Exception:

        logger.exception(
            "[Embeddings] Failed to materialize embedding iterable."
        )

        return []

    return get_embeddings(
        values
    )


# =========================================================
# EMBEDDING DIMENSION
# =========================================================

def embedding_dimension() -> int:
    """
    Return the embedding dimension.

    This loads the model lazily if necessary.

    Returns:
        Dimension > 0 when available, otherwise 0.
    """

    global _embedding_dimension

    if _embedding_dimension is not None:
        return int(
            _embedding_dimension
        )

    model = _load_embedding_model()

    if model is None:
        return 0

    try:

        dimension = int(
            model.get_sentence_embedding_dimension()
        )

        _embedding_dimension = dimension

        return dimension

    except Exception:

        logger.exception(
            "[Embeddings] Failed to determine embedding dimension."
        )

        return 0


# =========================================================
# AVAILABILITY
# =========================================================

def embedding_available() -> bool:
    """
    Check whether the local embedding engine can currently
    generate embeddings.

    This intentionally loads the model lazily.
    """

    model = _load_embedding_model()

    return model is not None


# =========================================================
# STATUS
# =========================================================

def embedding_status() -> dict:
    """
    Return diagnostic information without exposing the model object.
    """

    return {
        "available": _embedding_model is not None,
        "failed": _embedding_failed,
        "model": (
            _embedding_model_name
            or embedding_model_name()
        ),
        "dimension": (
            int(_embedding_dimension)
            if _embedding_dimension is not None
            else 0
        ),
        "device": (
            _embedding_device
            or embedding_device()
        ),
        "batch_size": embedding_batch_size(),
        "max_length": embedding_max_length(),
    }


# =========================================================
# CACHE CLEAR
# =========================================================

def clear_embedding_model_cache() -> None:
    """
    Release the local embedding model from memory.

    Useful for:
        - tests
        - maintenance
        - memory-constrained workers
        - controlled model switching

    This does not delete downloaded model files from disk.
    """

    global _embedding_model
    global _embedding_model_name
    global _embedding_dimension
    global _embedding_device
    global _embedding_failed

    with _embedding_lock:

        model = _embedding_model

        _embedding_model = None
        _embedding_model_name = None
        _embedding_dimension = None
        _embedding_device = None
        _embedding_failed = False

        if model is not None:

            try:
                del model

            except Exception:
                pass

        # Best-effort garbage collection.
        try:
            import gc

            gc.collect()

        except Exception:
            pass

        # Best-effort Torch cache cleanup.
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        except Exception:
            pass

    logger.info(
        "[Embeddings] Local embedding model cache cleared."
    )


# =========================================================
# COMPATIBILITY ALIASES
# =========================================================
#
# Keep common names available so existing ARIA modules do not
# require unnecessary changes.
# =========================================================

get_local_embedding = get_embedding

get_local_embeddings = get_embeddings

get_embedding_dimension = embedding_dimension


# =========================================================
# MODULE DIAGNOSTICS
# =========================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    logger.info(
        "[Embeddings] Configuration: %s",
        embedding_status()
    )