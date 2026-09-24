"""Embedding providers.

Local and free, deliberately. `bge-small-en-v1.5` runs on CPU, costs nothing per
call, and never rate-limits — which matters because embedding ~20k chunks
through a metered API is both a bill and an afternoon of backoff handling. It is
also 384-dimensional, and that is not incidental: Supabase's free tier is
500 MB, and 768-dim vectors over this corpus would not fit alongside the text.

The `hash` provider is a deterministic stand-in with **no semantic meaning**. It
exists so CI and a fresh clone can exercise the whole pipeline without
downloading a model. Retrieval quality on it is chance, and the eval harness
refuses to report retrieval numbers while it is active.

Document and query embeddings are distinguished. BGE and E5 models expect an
instruction prefix on queries only; omitting it costs several points of recall,
and it is the kind of thing that silently degrades a system for months.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Literal

from finlens.config import Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

InputType = Literal["document", "query"]

# The prefix BAAI publish for bge-* retrieval. Applied to queries only.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingProvider(ABC):
    """Interface every provider implements."""

    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str], *, input_type: InputType = "document") -> list[list[float]]:
        """Embed a batch. Returns one unit-normalised vector per input."""

    def embed_one(self, text: str, *, input_type: InputType = "document") -> list[float]:
        return self.embed([text], input_type=input_type)[0]

    @property
    def is_semantic(self) -> bool:
        """False for stand-ins whose output carries no meaning.

        The eval harness reads this to decide whether retrieval numbers are
        worth reporting at all.
        """
        return True


def _normalise(vector: list[float]) -> list[float]:
    """Unit-normalise, so cosine similarity reduces to a dot product."""
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


class SentenceTransformerProvider(EmbeddingProvider):
    """Local CPU embeddings. The production default."""

    name = "sentence-transformers"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "the sentence-transformers provider needs `pip install 'finlens[embed]'`"
            ) from exc

        log.info("embed.loading_model", model=model)
        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self._query_prefix = BGE_QUERY_PREFIX if "bge" in model.lower() else ""

    def embed(self, texts: list[str], *, input_type: InputType = "document") -> list[list[float]]:
        if not texts:
            return []
        prepared = [f"{self._query_prefix}{t}" for t in texts] if input_type == "query" else texts
        vectors = self._model.encode(
            prepared, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(x) for x in vector] for vector in vectors]


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic hashed bag-of-words. Offline stand-in; not semantic.

    Tokens are hashed into a fixed-width vector with signed contributions, which
    gives *lexical* overlap — a query sharing rare words with a chunk scores
    above chance — but no synonymy and no compositional meaning. Enough to
    exercise the plumbing, never enough to evaluate retrieval.
    """

    name = "hash"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str], *, input_type: InputType = "document") -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in text.lower().split():
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            # Signed, so unrelated tokens can cancel. Without this every vector
            # accumulates in the same direction and everything looks similar.
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        return _normalise(vector)

    @property
    def is_semantic(self) -> bool:
        return False


def get_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Build the configured provider.

    Falls back to `hash` only when sentence-transformers is genuinely
    unavailable, and says so loudly — a silent downgrade would make every
    retrieval number in the report meaningless without anyone noticing.
    """
    settings = settings or get_settings()

    if settings.embedding_provider == "sentence-transformers":
        try:
            return SentenceTransformerProvider(model=settings.embedding_model)
        except RuntimeError as exc:
            log.error(
                "embed.falling_back_to_hash",
                reason=str(exc),
                detail="retrieval quality will be chance; install finlens[embed]",
            )
            return HashEmbeddingProvider(dim=settings.embedding_dim)

    log.warning(
        "embed.using_hash_provider",
        detail="deterministic stand-in with no semantic meaning; retrieval quality is chance",
    )
    return HashEmbeddingProvider(dim=settings.embedding_dim)
