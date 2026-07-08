"""Embedder factory — provide unified embedding interface.

Supports:
  - Real models via sentence-transformers (set EMBEDDING_MODEL env var)
  - Pseudo-embedding fallback (SHA256 hash → deterministic vector)

Usage:
    from rag.embedder import get_embedder
    embed = get_embedder()          # auto-detect from env
    embed = get_embedder(dim=768)   # specify dimension
    vec = embed("hello world")      # → list[float]
"""

import hashlib
import os
from collections.abc import Callable


def create_pseudo_embedder(dim: int = 64) -> Callable[[str], list[float]]:
    """Create a deterministic pseudo-embedder from SHA256 hash.

    Maps text to a fixed [-1, 1] vector. No semantic meaning — only useful
    as a placeholder until a real embedding model is configured.
    """

    def embed(text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk = max(1, len(h) // dim)
        vec = []
        for i in range(dim):
            segment = h[i * chunk : (i + 1) * chunk]
            val = int(segment, 16) / (16 ** len(segment))
            vec.append(val * 2.0 - 1.0)
        return vec

    return embed


def create_sentence_transformer_embedder(
    model_name: str = "all-MiniLM-L6-v2",
) -> Callable[[str], list[float]]:
    """Create an embedder using sentence-transformers.

    Args:
        model_name: HuggingFace model ID (default: all-MiniLM-L6-v2, 384-dim).

    Returns:
        Callable that maps text to embedding vector.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. "
            "Run: pip install sentence-transformers"
        )

    model = SentenceTransformer(model_name)

    def embed(text: str) -> list[float]:
        return model.encode(text, normalize_embeddings=True).tolist()

    return embed


def get_embedder(
    model_name: str | None = None,
    dim: int = 64,
) -> Callable[[str], list[float]]:
    """Get an embedder based on environment or parameters.

    Priority:
      1. Explicit model_name parameter (e.g. "all-MiniLM-L6-v2")
      2. EMBEDDING_MODEL environment variable
      3. Fallback to pseudo-embedder with given dim

    Args:
        model_name: Optional model name/ID. Overrides env var.
        dim: Embedding dimension for pseudo-embedder fallback.

    Returns:
        Callable[[str], list[float]]
    """
    name = model_name or os.environ.get("EMBEDDING_MODEL", "")

    if name and name.lower() != "pseudo":
        try:
            return create_sentence_transformer_embedder(name)
        except ImportError:
            import warnings
            warnings.warn(
                f"sentence-transformers not available, falling back to pseudo-embedder. "
                f"Install with: pip install sentence-transformers"
            )

    emb = create_pseudo_embedder(dim)
    return emb
