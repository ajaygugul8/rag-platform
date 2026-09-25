"""
Schema (Phase 1 foundation + Phase 3 hybrid-search column).

Design notes:
- `Document` and `Chunk` are separated because the ingestion pipeline
  (Phase 2) produces many chunks per document, each independently
  embedded and independently retrievable, but citations need to trace
  back to the parent document (filename, upload time, source).
- `Chunk.embedding` uses pgvector's native vector type so similarity
  search can use a real ANN index (ivfflat/hnsw) instead of doing
  cosine similarity in Python.
- `content_tsv` is a generated tsvector column for BM25-style keyword
  search (Phase 3: Hybrid Search) — declared now so the migration story
  is one shot instead of a later ALTER.
- Every table carries `created_at`/`updated_at` for observability and
  auditability, per the non-functional requirements.
"""

import uuid
from datetime import datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-form metadata: department, category, source system, uploader, etc.
    # JSONB so metadata filtering (spec section 5) doesn't require schema
    # migrations every time a new filterable field is needed.
    doc_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # order within document
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False, default="text", server_default="text")
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("chunks.id", ondelete="SET NULL"), 
        nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim), nullable=True)

    # Generated column for BM25-style keyword search (Phase 3: Hybrid
    # Search). PostgreSQL maintains this automatically whenever `content`
    # changes — we never write to it directly. GIN index below makes
    # `@@ plainto_tsquery(...)` fast at query time.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        # HNSW index for vector similarity search is created at app startup in main.py rather than here, since pgvector's index DDL isn't
        # expressible through SQLAlchemy's Index() the way a plain GIN index is. See main.py for details.
        # Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_chunks_modality", "modality"),
        # Vector ANN index (HNSW) is created at app startup in main.py rather than here, since pgvector's index DDL isn't expressible through
        # SQLAlchemy's Index() the way a plain GIN index is. See main.py for details.
        # Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
        # Index("ix_chunks_parent_chunk_id", "parent_chunk_id"),
        # Index("ix_chunks_modality", "modality"),
        # Index("ix_chunks_parent_chunk_id", "parent_chunk_id"), 
        # Vector ANN index (HNSW) is created at app startup in main.py rather
        # than here, since pgvector's index DDL isn't expressible through
        # SQLAlchemy's Index() the way a plain GIN index is.
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_useful: Mapped[bool] = mapped_column(nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationTurn(Base):
    """One turn (user question or assistant answer) in a chat session.

    Kept deliberately minimal — this is short-term conversational memory
    for follow-up-question rewriting (Phase 4), not a full chat-history
    product feature. `session_id` is client-supplied (no server-side
    session management); a UUID the client generates per conversation.
    """

    __tablename__ = "conversation_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_conversation_turns_session_id", "session_id", "created_at"),)

class ChatMessage(Base):
    """Frontend conversation history — one row per user/assistant turn.

    Kept separate from `conversation_turns` on purpose:
      - conversation_turns feeds query rewriting; stays plain (role, content)
      - chat_messages stores the full response payload (citations, abstained,
        resolved_query) so the sidebar can restore a conversation exactly as
        it looked when the user last saw it

    session_id is client-generated and reused as the conversation key in the
    frontend — one identifier, not two.
    """
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )