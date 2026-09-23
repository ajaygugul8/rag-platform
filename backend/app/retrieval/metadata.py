"""
Turns a flat filter dict (e.g. {"department": "engineering", "category":
"policy"}) into a JSONB containment predicate against Document.doc_metadata.
Shared by vector, keyword, and hybrid retrieval so all three respect the
same filter semantics — per spec section 5 ("Filter retrieval by document,
source, department/category, date or other metadata").
"""

from sqlalchemy import ColumnElement, and_, cast
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import Document


def build_metadata_filter(filters: dict | None) -> ColumnElement | None:
    if not filters:
        return None
    return Document.doc_metadata.op("@>")(cast(filters, JSONB))


def combine_filters(*clauses: ColumnElement | None) -> ColumnElement | None:
    active = [c for c in clauses if c is not None]
    if not active:
        return None
    return and_(*active)
