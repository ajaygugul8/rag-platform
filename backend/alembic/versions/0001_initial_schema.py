"""Baseline schema: documents, chunks, feedback, conversation_turns

Revision ID: 0001
Revises:
Create Date: 2026-09-21

This migration documents the schema as it exists after Phases 1-4, built
incrementally via SQLAlchemy's create_all() plus ad-hoc startup DDL before
Alembic was introduced. It is NOT meant to be run with `alembic upgrade
head` against the existing dev database (that would try to CREATE tables
that already exist and fail) - on an existing database, run:

    alembic stamp head

which marks the database as already being at this revision without
executing any of the SQL below. Only a genuinely fresh database (a new
developer's machine, CI, a clean deployment) should actually run
`alembic upgrade head` starting from this revision.

From this point forward, every schema change is a new revision generated
with `alembic revision --autogenerate -m "description"` and applied with
`alembic upgrade head` - no more silent create_all() drift.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, TSVECTOR
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Must match app/config.py's EMBEDDING_DIM default. If your .env overrides
# EMBEDDING_DIM, adjust this migration (or, better, make embedding_dim a
# migration parameter) before running on a fresh database.
EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    document_status = sa.Enum("uploaded", "processing", "ready", "failed", name="document_status")
    document_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("status", document_status, nullable=False, server_default="uploaded"),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("doc_metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("section_title", sa.String(512), nullable=True),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "content_tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("is_useful", sa.Boolean, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_conversation_turns_session_id", "conversation_turns", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("conversation_turns")
    op.drop_table("feedback")
    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("documents")
    sa.Enum(name="document_status").drop(op.get_bind(), checkfirst=True)