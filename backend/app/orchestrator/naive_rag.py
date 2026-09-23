"""
The naive baseline pipeline, per spec section 5: "Implement a simple
retrieve -> prompt -> generate flow first, then improve it." This module
stays intact even after Phase 3/4 add hybrid retrieval, reranking, and
query transformation — those live in a separate `improved_rag.py`
orchestrator so the two can be compared side by side, which is exactly
what the spec's evaluation phase (and acceptance criteria: "a comparison
of baseline RAG versus the improved pipeline") requires.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.embeddings.provider import get_embedding_provider
from app.generation.llm_client import LLMClient
from app.generation.prompt import SYSTEM_PROMPT, build_user_prompt
from app.generation.providers import get_llm_client
from app.observability.tracing import trace_stage
from app.retrieval.vector_store import RetrievedChunk, vector_search

# Below this similarity score, we treat retrieval as "no real evidence"
# and abstain rather than let the LLM generate from weak/irrelevant
# context.
#
# Measured directly against this project's corpus and embedding model
# (BAAI/bge-small-en-v1.5) rather than guessed: a genuinely relevant
# question scored 0.84, while two deliberately irrelevant questions
# ("What is the company's stock price?", "What is the capital of
# France?") scored 0.50 and 0.38 respectively — both comfortably ABOVE
# the old 0.35 default, meaning this pipeline was answering unrelated
# questions with false confidence. Small sentence-embedding models suffer
# from "anisotropy": generic English text tends to cluster together in
# embedding space, producing a similarity floor well above 0 for
# completely unrelated content. 0.6 sits with margin above both measured
# noise samples and below the real signal, but this is still a 3-point
# calibration, not a rigorous one — revisit once the Phase 5 eval set
# provides enough true-positive/true-negative pairs to tune this properly.
MIN_RELEVANCE_SCORE = 0.6

ABSTENTION_MESSAGE = "I don't have enough information in the knowledge base to answer that."


@dataclass
class RagAnswer:
    answer: str
    citations: list[RetrievedChunk]
    abstained: bool


def answer_query(
    db: Session,
    question: str,
    document_ids: list[UUID] | None = None,
    llm_client: LLMClient | None = None,
) -> RagAnswer:
    embedding_provider = get_embedding_provider()
    llm_client = llm_client or get_llm_client()

    with trace_stage("embed_query", question_length=len(question)):
        query_embedding = embedding_provider.embed_query(question)

    with trace_stage("vector_search", top_k=settings.retrieval_top_k):
        chunks = vector_search(
            db,
            query_embedding,
            top_k=settings.retrieval_top_k,
            document_ids=document_ids,
        )

    relevant_chunks = [c for c in chunks if c.score >= MIN_RELEVANCE_SCORE]

    if not relevant_chunks:
        return RagAnswer(answer=ABSTENTION_MESSAGE, citations=[], abstained=True)

    user_prompt = build_user_prompt(question, relevant_chunks)

    with trace_stage("generate", prompt_chars=len(user_prompt)):
        answer_text = llm_client.generate(SYSTEM_PROMPT, user_prompt)

    # The system prompt instructs the LLM to emit ABSTENTION_MESSAGE
    # verbatim when the retrieved context doesn't answer the question.
    # That's a legitimate refusal, but the flag above this point is only
    # set when *retrieval* comes up empty — so reconcile the flag with
    # what the LLM actually said.
    abstained = ABSTENTION_MESSAGE.lower() in answer_text.lower()

    return RagAnswer(answer=answer_text, citations=relevant_chunks, abstained=abstained)