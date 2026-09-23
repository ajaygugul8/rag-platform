import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import DocumentResponse
from app.core.exceptions import FileTooLargeError, UnsupportedFileTypeError
from app.core.security import require_auth
from app.db.models import Document, DocumentStatus
from app.db.session import SessionLocal, get_db
from app.ingestion.pipeline import run_ingestion
from app.ingestion.storage import save_file
from app.ingestion.validation import validate_upload

logger = logging.getLogger("rag.api.documents")

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(require_auth)])


def _ingest_in_background(document_id) -> None:
    """Runs in a FastAPI BackgroundTask, which executes after the response
    is sent but still within the same process/event loop. The request-scoped
    `db` session is already closed by then, so this opens its own â€” never
    share a session across a request/background boundary.

    NOTE: this is single-process background execution, fine for a demo.
    Phase 6 swaps this for a real task queue (e.g. Celery/RQ/arq) so
    ingestion survives a process restart and can be scaled independently
    of the API â€” the call site (`background_tasks.add_task(...)` below)
    is the only place that changes.
    """
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is not None:
            run_ingestion(db, document)
    finally:
        db.close()


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    metadata: str = Form(default="{}"),
    db: Session = Depends(get_db),
) -> Document:
    content = await file.read()

    try:
        validate_upload(file.filename or "unknown", file.content_type or "", len(content))
    except (UnsupportedFileTypeError, FileTooLargeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        parsed_metadata = json.loads(metadata) if metadata else {}
        if not isinstance(parsed_metadata, dict):
            raise ValueError("metadata must be a JSON object")
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'metadata' must be a valid JSON object string: {exc}",
        ) from exc

    document = Document(
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        storage_path="",  # set below, after we have the generated id
        status=DocumentStatus.UPLOADED,
        doc_metadata=parsed_metadata,
    )
    db.add(document)
    db.flush()  # assigns document.id without committing yet

    document.storage_path = save_file(document.id, document.filename, content)
    db.commit()
    db.refresh(document)

    logger.info("document_uploaded", extra={"document_id": str(document.id), "doc_filename": document.filename})

    background_tasks.add_task(_ingest_in_background, document.id)
    return document


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return list(db.scalars(select(Document).order_by(Document.created_at.desc())))


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db)) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document
