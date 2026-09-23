"""
The "improved" pipeline: [conversation-aware] query rewriting -> optional
multi-query expansion -> hybrid retrieval -> metadata filtering -> reranking
-> contextual compression -> grounded generation.

Kept as a separate module from naive_rag.py rather than replacing it — the
spec's acceptance criteria explicitly require "a comparison of baseline
RAG versus the improved pipeline using evaluation metrics" (Phase 5), and
you can't compare two things that share one implementation.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.conversation.history import add_turn, get_recent_history
from app.embeddings.provider import get_embedding_provider
from app.generation.llm_client import LLMClient
from app.generation.prompt import SYSTEM_PROMPT, build_user_prompt
from app.generation.providers import get_llm_client
from app.observability.tracing import trace_stage
from app.retrieval.compression import compress_context
from app.retrieval.hybrid import hybrid_search
from app.retrieval.keyword_store import keyword_search
from app.retrieval.query_transform import expand_queries, rewrite_query
from app.retrieval.reranker import rerank
from app.retrieval.vector_store import RetrievedChunk, vector_search

# Fix (round 1): gate abstention on RAW (non-normalized) vector cosine
# similarity of the actual resolved question - the same absolute, proven
# 0-1 scale naive_rag.py uses. Measured directly against this project's
# corpus: a genuinely relevant question scored 0.84, while "What is the
# company's stock price?" and "What is the capital of France?" scored
# 0.50 and 0.38 - both above the old 0.35 default. 0.6 sits with margin
# above both measured noise samples and below the real signal.
#
# Fix (round 2, after running the Phase 5 eval harness): round 1 gated on
# ONLY the original question's plain embedding, computed BEFORE
# multi-query expansion or hybrid/keyword search ever ran - so it threw
# away everything the rest of the pipeline found. Round 2 fixes this:
#   1. Vector relevance is now the MAX raw cosine similarity across ALL
#      multi-query paraphrases, not just the original wording.
#   2. A raw keyword signal is added as an OR condition: if the ORIGINAL
#      question gets any nonzero PostgreSQL ts_rank score, that's treated
#      as sufficient evidence on its own.
RAW_VECTOR_MIN_RELEVANCE_SCORE = 0.6

ABSTENTION_MESSAGE = "I don't have enough information in the knowledge base to answer that."


@dataclass
class RagAnswer:
    answer: str
    citations: list[RetrievedChunk]
    abstained: bool
    resolved_query: str  # the query actually used for retrieval, after rewriting


def _retrieve(
    db: Session,
    question: str,
    document_ids: list[UUID] | None,
    metadata_filters: dict | None,
    llm_client: LLMClient,
) -> tuple[list[RetrievedChunk], float]:
    embedding_provider = get_embedding_provider()
    resolved_embedding = embedding_provider.embed_query(question)

    # Raw keyword signal on the ORIGINAL question only (not paraphrases -
    # an LLM rewrite could easily drop or alter an exact code like
    # "SEC-104"). Any nonzero ts_rank means a real term literally matched.
    keyword_top = keyword_search(
        db, question, top_k=1, document_ids=document_ids, metadata_filters=metadata_filters
    )
    has_keyword_match = bool(keyword_top) and keyword_top[0].score > 0.0

    queries = (
        expand_queries(llm_client, question)
        if settings.enable_multi_query
        else [question]
    )

    # Raw vector relevance is the MAX across the original question AND
    # every multi-query paraphrase.
    raw_vector_relevance = 0.0
    by_id: dict = {}
    for q in queries:
        q_embedding = (
            resolved_embedding if q == question else embedding_provider.embed_query(q)
        )

        raw_top = vector_search(db, q_embedding, top_k=1, document_ids=document_ids, metadata_filters=metadata_filters)
        if raw_top:
            raw_vector_relevance = max(raw_vector_relevance, raw_top[0].score)

        results = hybrid_search(
            db,
            query_text=q,
            query_embedding=q_embedding,
            top_k=settings.retrieval_top_k,
            alpha=settings.hybrid_alpha,
            document_ids=document_ids,
            metadata_filters=metadata_filters,
        )
        for chunk in results:
            # Keep the best-scoring copy across query variants.
            existing = by_id.get(chunk.chunk_id)
            if existing is None or chunk.score > existing.score:
                by_id[chunk.chunk_id] = chunk

    candidates = sorted(by_id.values(), key=lambda c: c.score, reverse=True)

    # Combined relevance: either signal being strong enough is sufficient.
    relevance = (
        RAW_VECTOR_MIN_RELEVANCE_SCORE if has_keyword_match else raw_vector_relevance
    )
    return candidates, relevance


def answer_query(
    db: Session,
    question: str,
    document_ids: list[UUID] | None = None,
    metadata_filters: dict | None = None,
    session_id: str | None = None,
    llm_client: LLMClient | None = None,
) -> RagAnswer:
    llm_client = llm_client or get_llm_client()

    # Conversation-aware retrieval: resolve follow-up questions against
    # prior turns BEFORE embedding/retrieval.
    if session_id:
        with trace_stage("history_lookup"):
            history = get_recent_history(db, session_id)
    else:
        history = ""

    if history:
        with trace_stage("rewrite_query", history_chars=len(history)):
            resolved_query = rewrite_query(llm_client, question, history)
    else:
        resolved_query = question

    with trace_stage("retrieve", multi_query=settings.enable_multi_query):
        candidates, raw_relevance = _retrieve(
            db, resolved_query, document_ids, metadata_filters, llm_client
        )

    # If the query was rewritten, also check the ORIGINAL question's raw
    # vector relevance. Rewriting is helpful for genuine follow-ups ("what
    # about sick leave?") but can over-eagerly inject context and corrupt a
    # standalone question ("...in the SmartHome Hub document?" appended to
    # an unrelated question). Letting either form pass the gate — matching
    # the same OR-logic already used for multi-query paraphrases — closes
    # that failure mode without disabling rewriting for real follow-ups.
    if resolved_query != question:
        with trace_stage("rewrite_safety_net"):
            orig_embedding = get_embedding_provider().embed_query(question)
            orig_top = vector_search(
                db, orig_embedding, top_k=1, document_ids=document_ids, metadata_filters=metadata_filters
            )
            orig_relevance = orig_top[0].score if orig_top else 0.0
            raw_relevance = max(raw_relevance, orig_relevance)

    if not candidates or raw_relevance < RAW_VECTOR_MIN_RELEVANCE_SCORE:
        if session_id:
            add_turn(db, session_id, "user", question)
            add_turn(db, session_id, "assistant", ABSTENTION_MESSAGE)
        return RagAnswer(
            answer=ABSTENTION_MESSAGE,
            citations=[],
            abstained=True,
            resolved_query=resolved_query,
        )

    if settings.rerank_enabled:
        with trace_stage("rerank", top_n=settings.rerank_top_n):
            final_chunks = rerank(
                resolved_query, candidates, top_n=settings.rerank_top_n
            )
    else:
        final_chunks = candidates

    with trace_stage("compress", budget=settings.context_token_budget):
        relevant_chunks = compress_context(
            final_chunks, settings.context_token_budget
        )

    if not relevant_chunks:
        if session_id:
            add_turn(db, session_id, "user", question)
            add_turn(db, session_id, "assistant", ABSTENTION_MESSAGE)
        return RagAnswer(
            answer=ABSTENTION_MESSAGE,
            citations=[],
            abstained=True,
            resolved_query=resolved_query,
        )

    user_prompt = build_user_prompt(resolved_query, relevant_chunks, history)

    with trace_stage("generate", prompt_chars=len(user_prompt)):
        answer_text = llm_client.generate(SYSTEM_PROMPT, user_prompt)

    if session_id:
        add_turn(db, session_id, "user", question)
        add_turn(db, session_id, "assistant", answer_text)

    abstained = ABSTENTION_MESSAGE.lower() in answer_text.lower()

    return RagAnswer(
        answer=answer_text,
        citations=relevant_chunks,
        abstained=abstained,
        resolved_query=resolved_query,
    )