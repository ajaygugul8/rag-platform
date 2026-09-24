"""add chunks.modality and chunks.parent_chunk_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23

Phase 2 of the multimodal upgrade: chunks gain `modality`
('text' | 'table' | 'image') and a self-referential `parent_chunk_id` for
linking table/image chunks back to the surrounding text chunk.

Existing rows default to modality='text', parent_chunk_id=NULL — no data
migration needed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("modality", sa.String(16), nullable=False, server_default="text"),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "parent_chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_modality", "chunks", ["modality"])


def downgrade() -> None:
    op.drop_index("ix_chunks_modality", table_name="chunks")
    op.drop_column("chunks", "parent_chunk_id")
    op.drop_column("chunks", "modality")