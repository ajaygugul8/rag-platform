"""
The ingestion pipeline. This is the "Baseline RAG" half of Phase 2's
indexing side: given an already-uploaded Document row, read its file off
disk, parse it, clean it, chunk it, embed the chunks, and persist them.

Failure handling: per spec ("handle ingestion failures gracefully"), any
IngestionError caught here marks the Document FAILED with a reason instead
of raising past the caller — a bad file must not crash the request or
leave the document stuck in PROCESSING forever.
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import IngestionError
from app.db.models import Chunk, Document, DocumentStatus
from app.embeddings.provider import get_embedding_provider
from app.ingestion.chunking import ChunkingStrategy, chunk_document
from app.ingestion.cleaning import clean_text
from app.ingestion.parsers import ParsedUnit, parse_document
from app.observability.tracing import trace_stage

logger = logging.getLogger("rag.ingestion.pipeline")

DEFAULT_CHUNK_SIZE = 300
DEFAULT_CHUNK_OVERLAP = 50


def run_ingestion(db: Session, document: Document, strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE) -> None:
    document.status = DocumentStatus.PROCESSING
    db.commit()
    doc_id = str(document.id)

    try:
        with trace_stage("ingestion_parse", document_id=doc_id):
            content = Path(document.storage_path).read_bytes()
            parsed = parse_document(document.content_type, content, doc_id)
            # Phase 2: only text_units are routed to chunks. table_units
            # and picture_units are captured by the parser but not yet
            # persisted — that's Phase 3 (tables) and Phase 4 (pictures).
            cleaned_units = [
                ParsedUnit(clean_text(u.text), u.page_number, u.section_title)
                for u in parsed.text_units
            ]

        with trace_stage("ingestion_chunk", document_id=doc_id):
            raw_chunks = chunk_document(cleaned_units, strategy, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
            if not raw_chunks:
                raise IngestionError(doc_id, "Chunking produced zero chunks.")

        with trace_stage("ingestion_embed", document_id=doc_id, chunk_count=len(raw_chunks)):
            provider = get_embedding_provider()
            vectors = provider.embed_documents([c.text for c in raw_chunks])

        # Wipe any previous chunks (re-ingestion / retry case).
        for old_chunk in list(document.chunks):
            db.delete(old_chunk)
        db.flush()

        for index, (raw_chunk, vector) in enumerate(zip(raw_chunks, vectors)):
            db.add(
                Chunk(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    content=raw_chunk.text,
                    chunk_index=index,
                    page_number=raw_chunk.page_number,
                    section_title=raw_chunk.section_title,
                    token_count=raw_chunk.token_count,
                    chunk_metadata={"chunking_strategy": strategy.value},
                    embedding=vector,
                )
            )

        document.status = DocumentStatus.READY
        document.failure_reason = None
        db.commit()
        logger.info(
            "ingestion_succeeded",
            extra={"document_id": str(document.id), "chunk_count": len(raw_chunks)},
        )

    except IngestionError as exc:
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.failure_reason = str(exc)
        db.commit()
        logger.warning("ingestion_failed", extra={"document_id": str(document.id), "reason": str(exc)})

    except Exception as exc:  # noqa: BLE001 — never let ingestion crash the worker
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.failure_reason = f"Unexpected error: {exc}"
        db.commit()
        logger.error("ingestion_unexpected_error", extra={"document_id": str(document.id), "error": str(exc)})
