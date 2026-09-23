"""
Short-term conversation history, per spec: "Maintain short-term
conversation history while preventing irrelevant history from
overwhelming retrieval."

Deliberately bounded to the last N turns (`conversation_history_turns`)
rather than the full session — a long conversation's early turns are
usually irrelevant to the current follow-up and would only dilute the
query-rewriting prompt. This module is the only thing that touches
`ConversationTurn`; the orchestrator never queries the table directly.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ConversationTurn


def get_recent_history(db: Session, session_id: str) -> str:
    stmt = (
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
        .order_by(ConversationTurn.created_at.desc())
        .limit(settings.conversation_history_turns)
    )
    turns = list(reversed(db.scalars(stmt).all()))
    if not turns:
        return ""
    return "\n".join(f"{t.role}: {t.content}" for t in turns)


def add_turn(db: Session, session_id: str, role: str, content: str) -> None:
    db.add(ConversationTurn(session_id=session_id, role=role, content=content))
    db.commit()
