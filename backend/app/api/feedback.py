"""
POST /feedback — users mark an answer as useful/not useful, optionally
with a comment. Backed by the `feedback` table (app/db/models.py), which
has existed since Phase 1 but had no route writing to it until now.

Kept separate from /query rather than a field on the query request: a
feedback submission is a distinct user action that may happen seconds
or minutes after the answer was shown, and may be revised. Decoupling
the two means the query endpoint stays stateless and cache-friendly
(see app/core/cache.py) without feedback writes polluting its key.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import require_auth
from app.db.models import Feedback
from app.db.session import get_db

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackIn(BaseModel):
    query: str
    answer: str
    is_useful: bool
    comment: str | None = None


class FeedbackOut(BaseModel):
    id: str
    created_at: str


@router.post(
    "",
    response_model=FeedbackOut,
    status_code=201,
    dependencies=[Depends(require_auth)],
)
def post_feedback(payload: FeedbackIn, db: Session = Depends(get_db)) -> FeedbackOut:
    row = Feedback(
        query=payload.query,
        answer=payload.answer,
        is_useful=payload.is_useful,
        comment=payload.comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FeedbackOut(id=str(row.id), created_at=row.created_at.isoformat())