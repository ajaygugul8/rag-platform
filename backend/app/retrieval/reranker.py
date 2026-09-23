"""
Reranking, per spec: "Apply a reranker to reorder candidate chunks before
generation." Bi-encoder retrieval (vector search) is fast but approximate —
it scores query and chunk independently. A cross-encoder scores the
(query, chunk) pair jointly, which is slower but meaningfully more
accurate, so it's applied only to the small candidate set hybrid search
already narrowed down, not the whole corpus.

Local model (BAAI/bge-reranker-base) by default so reranking works with
zero API keys, same reasoning as the local embedding provider. Lazily
loaded and cached at module level.
"""

from dataclasses import replace
from functools import lru_cache

from app.config import settings
from app.retrieval.vector_store import RetrievedChunk


@lru_cache
def _load_reranker():
    from sentence_transformers import CrossEncoder

    # Same fix as app/embeddings/local.py: force the non-meta-device load
    # path so a flaky/partial download can't produce "Cannot copy out of
    # meta tensor; no data!" instead of a normal retry-able download error.
    return CrossEncoder(
        "BAAI/bge-reranker-base",
        device="cpu",
        automodel_args={"low_cpu_mem_usage": False},
    )


def rerank(query: str, chunks: list[RetrievedChunk], top_n: int | None = None) -> list[RetrievedChunk]:
    if not chunks:
        return chunks

    top_n = top_n or settings.rerank_top_n
    model = _load_reranker()

    pairs = [(query, c.content) for c in chunks]
    raw_scores = model.predict(pairs)

    reranked = [replace(chunk, score=float(score)) for chunk, score in zip(chunks, raw_scores)]
    reranked.sort(key=lambda c: c.score, reverse=True)
    return reranked[:top_n]