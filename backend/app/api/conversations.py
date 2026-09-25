"""
GET /conversations and GET /conversations/{session_id}

Backs the frontend's sidebar history. Reads the chat_messages table
(see the ChatMessage model in app/db/models.py and alembic revision
0003), which is written by POST /query.

Kept as its own router/table rather than reusing `conversation_turns`
on purpose: conversation_turns feeds the improved pipeline's query
rewriting logic and must stay plain (role, content) so it can be
dropped straight into an LLM prompt. chat_messages stores the full
response payload (citations, abstained, resolved_query) so the frontend
can restore a conversation exactly as it looked when the user left it.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_auth
from app.db.models import ChatMessage
from app.db.session import get_db

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
def list_conversations(db: Session = Depends(get_db)):
    """One row per session_id: title = first user question, sorted by
    most recent activity. This is exactly what the frontend sidebar
    needs and nothing more — full message bodies are fetched lazily
    per-conversation via the endpoint below."""
    agg = (
        select(
            ChatMessage.session_id,
            func.max(ChatMessage.created_at).label("last_message_at"),
            func.count(ChatMessage.id).label("message_count"),
        )
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    rows = db.execute(select(agg)).all()

    result = []
    for row in rows:
        first_user_msg = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == row.session_id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.created_at.asc())
            .first()
        )
        title = first_user_msg.content[:60] if first_user_msg else "Conversation"
        result.append({
            "session_id": row.session_id,
            "title": title,
            "last_message_at": row.last_message_at,
            "message_count": row.message_count,
        })

    result.sort(key=lambda r: r["last_message_at"], reverse=True)
    return result


@router.get("/{session_id}")
def get_conversation(session_id: str, db: Session = Depends(get_db)):
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    if not messages:
        raise HTTPException(
            status_code=404,
            detail="No conversation found for this session_id",
        )

    return [
        {
            "role": m.role,
            "content": m.content,
            "metadata": m.message_metadata,
            "created_at": m.created_at,
        }
        for m in messages
    ]