"""
Local 384-dimensional embedding generator using FastEmbed.
Ensures deterministic vector outputs compatible with PostgreSQL pgvector(384).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastembed import TextEmbedding

from apps.api.config import settings

logger = logging.getLogger(__name__)

# Expected vector dimension matching public.chunks.embedding
EMBEDDING_DIM = 384

_model_instance: Optional[TextEmbedding] = None


def get_embedding_model() -> TextEmbedding:
    """Retrieve or initialize the singleton FastEmbed model."""
    global _model_instance
    if _model_instance is None:
        model_name = settings.embedding_model or "sentence-transformers/all-MiniLM-L6-v2"
        logger.info("Initializing local FastEmbed embedding model: %s", model_name)
        _model_instance = TextEmbedding(model_name=model_name)
    return _model_instance


def embed_text(text: str) -> List[float]:
    """
    Generate a 384-dimensional embedding vector for a single text string.
    Raises ValueError on empty or whitespace-only input.
    """
    clean_text = text.strip() if text else ""
    if not clean_text:
        raise ValueError("Cannot generate embedding for empty or whitespace-only text.")

    model = get_embedding_model()
    embeddings = list(model.embed([clean_text]))
    vec = embeddings[0].tolist() if hasattr(embeddings[0], "tolist") else list(embeddings[0])

    if len(vec) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, got {len(vec)}"
        )
    return vec


def embed_batch(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of non-empty text strings.
    Empty texts must be filtered prior to calling this function.
    """
    if not texts:
        return []

    for idx, t in enumerate(texts):
        if not t or not t.strip():
            raise ValueError(f"Empty or whitespace-only text at index {idx} in batch.")

    model = get_embedding_model()
    embeddings = list(model.embed(texts))
    result: List[List[float]] = []
    for idx, e in enumerate(embeddings):
        vec = e.tolist() if hasattr(e, "tolist") else list(e)
        if len(vec) != EMBEDDING_DIM:
            raise RuntimeError(
                f"Embedding dimension mismatch at index {idx}: expected {EMBEDDING_DIM}, got {len(vec)}"
            )
        result.append(vec)
    return result


def format_vector_for_pg(vector: List[float]) -> str:
    """Format a float list into PostgreSQL pgvector text format: [x,y,z]."""
    return "[" + ",".join(str(x) for x in vector) + "]"

