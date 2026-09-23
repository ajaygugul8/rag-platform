"""
Keyword retrieval using PostgreSQL's built-in full-text search against the
`content_tsv` generated column. This isn't literal BM25 — Postgres' default
ranking (`ts_rank_cd`) uses a different weighting formula — but it's the
same idea (lexical/term-based matching) and needs zero extra infrastructure
(no Elasticsearch/OpenSearch cluster for a demo). The spec explicitly
allows this substitution: "a lightweight BM25 implementation" is a listed
option for the Keyword Search layer.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.retrieval.metadata import build_metadata_filter, combine_filters
from app.retrieval.vector_store import RetrievedChunk


def keyword_search(
    db: Session,
    query_text: str,
    top_k: int = 8,
    document_ids: list[UUID] | None = None,
    metadata_filters: dict | None = None,
) -> list[RetrievedChunk]:
    ts_query = func.plainto_tsquery("english", query_text)
    rank = func.ts_rank_cd(Chunk.content_tsv, ts_query)

    stmt = (
        select(Chunk, Document.filename, rank.label("rank"))
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.content_tsv.op("@@")(ts_query))
        .order_by(rank.desc())
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
            score=float(rank_value),
        )
        for chunk, filename, rank_value in rows
    ]
