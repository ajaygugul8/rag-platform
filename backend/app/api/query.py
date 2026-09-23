import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import CitationResponse, QueryRequest, QueryResponse
from app.core.cache import make_key, query_cache
from app.core.security import require_auth
from app.db.session import get_db
from app.observability.tracing import trace_stage
from app.orchestrator import improved_rag, naive_rag

logger = logging.getLogger("rag.api.query")

router = APIRouter(prefix="/query", tags=["query"], dependencies=[Depends(require_auth)])


@router.post("", response_model=QueryResponse)
def query(request: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
    # Response caching only applies to stateless queries — a session_id
    # means conversation history can change the resolved query between
    # calls, so those must always run fresh (see app/core/cache.py).
    cache_key = None
    if request.session_id is None:
        cache_key = make_key(
            "query_response", request.pipeline, request.question, request.document_ids, request.filters
        )
        cached = query_cache.get(cache_key)
        if cached is not None:
            logger.info("query_cache_hit", extra={"pipeline": request.pipeline})
            return QueryResponse(**cached)

    resolved_query = None
    with trace_stage("query_pipeline", pipeline=request.pipeline):
        if request.pipeline == "baseline":
            result = naive_rag.answer_query(db, request.question, document_ids=request.document_ids)
        else:
            result = improved_rag.answer_query(
                db,
                request.question,
                document_ids=request.document_ids,
                metadata_filters=request.filters,
                session_id=request.session_id,
            )
            resolved_query = result.resolved_query

    logger.info(
        "query_answered",
        extra={
            "pipeline": request.pipeline,
            "question_length": len(request.question),
            "abstained": result.abstained,
            "citation_count": len(result.citations),
        },
    )

    citations = [
        CitationResponse(
            document_id=c.document_id,
            filename=c.filename,
            page_number=c.page_number,
            section_title=c.section_title,
            score=round(c.score, 4),
            excerpt=c.content[:280] + ("..." if len(c.content) > 280 else ""),
        )
        for c in result.citations
    ]

    response = QueryResponse(
        answer=result.answer,
        abstained=result.abstained,
        pipeline=request.pipeline,
        resolved_query=resolved_query,
        citations=citations,
    )

    if cache_key is not None:
        query_cache.set(cache_key, response.model_dump())

    return response
