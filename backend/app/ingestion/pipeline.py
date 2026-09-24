"""
The ingestion pipeline. Given an already-uploaded Document row, read its
file off disk, parse it, clean it, chunk it (text + tables + images),
embed the chunks, and persist them.

Failure handling: per spec ("handle ingestion failures gracefully"), any
IngestionError caught here marks the Document FAILED with a reason instead
of raising past the caller — a bad file must not crash the request or
leave the document stuck in PROCESSING forever.
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import IngestionError
from app.db.models import Chunk, Document, DocumentStatus
from app.embeddings.provider import get_embedding_provider
from app.generation.vision import describe_image
from app.ingestion.chunking import (
    ChunkingStrategy,
    RawChunk,
    approx_token_count,
    chunk_document,
    chunk_tables,
)
from app.ingestion.cleaning import clean_text
from app.ingestion.parsers import (
    ParsedUnit,
    PictureUnit,
    extract_docx_alt_texts,
    parse_document,
)
from app.observability.tracing import trace_stage

logger = logging.getLogger("rag.ingestion.pipeline")

DEFAULT_CHUNK_SIZE = 300
DEFAULT_CHUNK_OVERLAP = 50

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _build_image_chunks(
    pictures: list[PictureUnit],
    document_id: str,
    images_root: Path,
) -> list[RawChunk]:
    """Convert PictureUnits into RawChunks with modality='image'.

    For each picture:
      - Calls the vision model to get a description (empty string on failure)
      - Saves the PNG to <images_root>/<document_id>/images/<idx>.png
      - Builds chunk content: [Image] + Description + Alt text

    Never raises — a failed description or failed save produces a chunk
    with whatever content is available. Ingestion as a whole succeeds even
    if every image fails.
    """
    results: list[RawChunk] = []
    doc_image_dir = images_root / document_id / "images"

    for idx, pic in enumerate(pictures):
        description = describe_image(pic.image_bytes)

        image_path_str: str | None = None
        try:
            doc_image_dir.mkdir(parents=True, exist_ok=True)
            image_file = doc_image_dir / f"{idx}.png"
            image_file.write_bytes(pic.image_bytes)
            image_path_str = str(image_file)
        except Exception as exc:
            logger.warning(
                "image_artifact_save_failed",
                extra={"document_id": document_id, "index": idx, "error": str(exc)},
            )

        # Natural-language content. The reranker is trained on text-text
        # pairs and scores poorly against markup-style prefixes like
        # "[Image]" — so the chunk reads as prose. Two anchor phrases
        # cover the two query types that target images:
        #   "This image depicts ..."         → "what does the image show?"
        #   "Alternate text for this image:" → "what is the alt text?"
        parts = []
        if pic.caption:
            parts.append(f"Alternate text for this image: {pic.caption}")
        if description:
            parts.append(f"This image depicts: {description}")
        else:
            parts.append("This image depicts: (description unavailable).")

        content = "\n\n".join(parts)

        results.append(
            RawChunk(
                text=content,
                page_number=pic.page_number,
                section_title=pic.section_title,
                token_count=approx_token_count(content),
                modality="image",
                metadata={
                    "image_path": image_path_str,
                    "vision_model": settings.ollama_vision_model if description else None,
                    "has_alt_text": bool(pic.caption),
                },
            )
        )

    return results


def run_ingestion(
    db: Session,
    document: Document,
    strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE,
) -> None:
    document.status = DocumentStatus.PROCESSING
    db.commit()
    doc_id = str(document.id)

    try:
        with trace_stage("ingestion_parse", document_id=doc_id):
            content = Path(document.storage_path).read_bytes()
            parsed = parse_document(document.content_type, content, doc_id)

            # DOCX alt text — Docling does not populate PictureItem.caption_text
            # for DOCX. python-docx does, via DrawingML docPr.descr. Apply
            # only if the counts match — a mismatch means Docling and
            # python-docx saw different image sets, so alignment is unsafe.
            if document.content_type == DOCX_CONTENT_TYPE and parsed.picture_units:
                alt_texts = extract_docx_alt_texts(content)
                if alt_texts and len(alt_texts) == len(parsed.picture_units):
                    for pu, alt in zip(parsed.picture_units, alt_texts):
                        if alt and not pu.caption:
                            pu.caption = alt
                elif alt_texts:
                    logger.info(
                        "alt_text_count_mismatch",
                        extra={
                            "document_id": doc_id,
                            "alt_count": len(alt_texts),
                            "picture_count": len(parsed.picture_units),
                        },
                    )

            cleaned_units = [
                ParsedUnit(clean_text(u.text), u.page_number, u.section_title)
                for u in parsed.text_units
            ]

        with trace_stage("ingestion_chunk", document_id=doc_id):
            text_chunks = chunk_document(
                cleaned_units, strategy, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP
            )
            table_chunks = chunk_tables(parsed.table_units)
            raw_chunks = text_chunks + table_chunks

        with trace_stage(
            "ingestion_describe_images",
            document_id=doc_id,
            image_count=len(parsed.picture_units),
        ):
            image_chunks = _build_image_chunks(
                parsed.picture_units, doc_id, Path(settings.upload_dir)
            )
            raw_chunks = raw_chunks + image_chunks

        if not raw_chunks:
            raise IngestionError(doc_id, "Chunking produced zero chunks.")

        with trace_stage(
            "ingestion_embed", document_id=doc_id, chunk_count=len(raw_chunks)
        ):
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
                    modality=raw_chunk.modality,
                    chunk_metadata={
                        "chunking_strategy": strategy.value,
                        **raw_chunk.metadata,
                    },
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
        logger.warning(
            "ingestion_failed",
            extra={"document_id": str(document.id), "reason": str(exc)},
        )

    except Exception as exc:  # noqa: BLE001 — never let ingestion crash the worker
        db.rollback()
        document.status = DocumentStatus.FAILED
        document.failure_reason = f"Unexpected error: {exc}"
        db.commit()
        logger.error(
            "ingestion_unexpected_error",
            extra={"document_id": str(document.id), "error": str(exc)},
        )