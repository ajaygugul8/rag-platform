"""
Hybrid search: run vector and keyword retrieval independently, then merge
by min-max normalizing each score list to [0, 1] and combining with a
configurable weight (HYBRID_ALPHA — 1.0 = pure vector, 0.0 = pure
keyword). Normalization matters because the two scores live on
incomparable scales (cosine similarity vs. ts_rank_cd); combining raw
values would let whichever score happens to have a larger numeric range
dominate regardless of `alpha`.

Chunks found by only one method still make it into the merged candidate
set (with the other method's score treated as 0) — a document that uses
exact terminology absent from typical training data (a product code, an
internal acronym) should still surface via keyword search even if the
embedding model doesn't rate it as semantically close.
"""

import logging
import re
from dataclasses import replace
from uuid import UUID

from sqlalchemy.orm import Session

from app.retrieval.keyword_store import keyword_search
from app.retrieval.vector_store import RetrievedChunk, vector_search

logger = logging.getLogger("rag.retrieval.hybrid")

_IMAGE_KEYWORDS = re.compile(
    r"\b(image|images|picture|pictures|chart|charts|figure|figures|"
    r"diagram|diagrams|graph|graphs|photo|photos|illustration|"
    r"illustrations|screenshot|screenshots)\b",
    re.IGNORECASE,
)

_IMAGE_CHUNK_PREFIXES = ("Alternate text for this image", "This image depicts")


def _min_max_normalize(scores: dict[UUID, float]) -> dict[UUID, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def hybrid_search(
    db: Session,
    query_text: str,
    query_embedding: list[float],
    top_k: int = 8,
    alpha: float = 0.5,
    candidate_multiplier: int = 3,
    document_ids: list[UUID] | None = None,
    metadata_filters: dict | None = None,
) -> list[RetrievedChunk]:
    candidate_k = top_k * candidate_multiplier

    vector_results = vector_search(
        db, query_embedding, candidate_k, document_ids, metadata_filters
    )
    keyword_results = keyword_search(
        db, query_text, candidate_k, document_ids, metadata_filters
    )

    vector_scores = _min_max_normalize({c.chunk_id: c.score for c in vector_results})
    keyword_scores = _min_max_normalize({c.chunk_id: c.score for c in keyword_results})

    by_id: dict[UUID, RetrievedChunk] = {c.chunk_id: c for c in vector_results}
    for c in keyword_results:
        by_id.setdefault(c.chunk_id, c)

    blended: list[RetrievedChunk] = []
    for chunk_id, chunk in by_id.items():
        v_score = vector_scores.get(chunk_id, 0.0)
        k_score = keyword_scores.get(chunk_id, 0.0)
        combined = alpha * v_score + (1 - alpha) * k_score
        blended.append(replace(chunk, score=combined))

    # Modality boost: when the query explicitly asks about an image,
    # multiply image-modality chunk scores so they compete with text
    # chunks that merely discuss images. Applied before sorting so a
    # low-scoring image chunk from deeper in the candidate pool can
    # rise into the top-k. Text-only queries are unaffected — the
    # block is skipped when no image keyword appears.
    if _IMAGE_KEYWORDS.search(query_text or ""):
        for i, c in enumerate(blended):
            if (c.content or "").startswith(_IMAGE_CHUNK_PREFIXES):
                blended[i] = replace(c, score=c.score * 2.5)

    blended.sort(key=lambda c: c.score, reverse=True)
    final = blended[:top_k]

    logger.info(
        "retrieval_results",
        extra={
            "n_candidates": len(blended),
            "n_returned": len(final),
            "top_score": round(final[0].score, 4) if final else None,
            "min_score": round(final[-1].score, 4) if final else None,
            "image_boost": bool(_IMAGE_KEYWORDS.search(query_text or "")),
        },
    )

    return final