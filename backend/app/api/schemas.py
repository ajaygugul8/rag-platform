import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    failure_reason: str | None
    doc_metadata: dict
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    app_env: str
    database: str


class QueryRequest(BaseModel):
    question: str
    pipeline: Literal["baseline", "improved"] = "improved"
    document_ids: list[uuid.UUID] | None = None
    filters: dict | None = None  # e.g. {"department": "engineering"}
    session_id: str | None = None  # client-generated; enables conversation-aware retrieval


class CitationResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    section_title: str | None
    score: float
    excerpt: str


class QueryResponse(BaseModel):
    answer: str
    abstained: bool
    pipeline: str
    resolved_query: str | None = None
    citations: list[CitationResponse]
