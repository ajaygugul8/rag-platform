"""
Vector similarity retrieval against pgvector using cosine distance.
Composes with keyword_store.py in hybrid.py (Phase 3) and stays available
on its own for the naive baseline orchestrator, so baseline vs. improved
pipelines can be compared head-to-head.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.retrieval.metadata import build_metadata_filter, combine_filters


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    content: str
    page_number: int | None
    section_title: str | None
    score: float  # similarity, higher is better (1 - cosine_distance)


def vector_search(
    db: Session,
    query_embedding: list[float],
    top_k: int = 8,
    document_ids: list[UUID] | None = None,
    metadata_filters: dict | None = None,
) -> list[RetrievedChunk]:
    """Return the top_k chunks most similar to query_embedding.

    `document_ids` restricts to specific documents; `metadata_filters`
    restricts by arbitrary doc_metadata fields (department, category,
    date, etc.) via JSONB containment. Both compose with AND.
    """
    distance = Chunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(Chunk, Document.filename, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .order_by(distance)
        .limit(top_k)
    )

    where_clause = combine_filters(
        Chunk.document_id.in_(document_ids) if document_ids else None,
        build_metadata_filter(metadata_filters),
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)

    rows = db.execute(stmt).all()

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            content=chunk.content,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            score=1 - distance_value,
        )
        for chunk, filename, distance_value in rows
    ]
