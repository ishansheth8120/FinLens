"""Chunking and embedding for the narrative half of the corpus.

Pipeline: `fct_filing_section` -> `chunking.chunk_section` -> `providers` ->
`store.VectorStore`. Each stage is independently runnable so a change to chunk
size does not force a re-parse of HTML, and a change of embedding model does not
force a re-chunk.
"""

from finlens.embed.chunking import Chunk, chunk_section, chunk_text
from finlens.embed.providers import EmbeddingProvider, get_provider
from finlens.embed.store import SearchHit, VectorStore

__all__ = [
    "Chunk",
    "EmbeddingProvider",
    "SearchHit",
    "VectorStore",
    "chunk_section",
    "chunk_text",
    "get_provider",
]
