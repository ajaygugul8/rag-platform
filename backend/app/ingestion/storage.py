"""
Local disk storage for Phase 1. Swappable: replace with an S3/GCS-backed
implementation behind the same `save_file(document_id, filename, content) -> path`
signature when moving off a single host — nothing above this layer needs to
change because callers only ever see a `storage_path` string.
"""

import uuid
from pathlib import Path

from app.config import settings


def save_file(document_id: uuid.UUID, filename: str, content: bytes) -> str:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename).suffix
    dest = upload_dir / f"{document_id}{suffix}"
    dest.write_bytes(content)
    return str(dest)
