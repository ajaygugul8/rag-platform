"""
Query transformation, per spec: "Demonstrate query rewriting, multi-query
or decomposition for difficult questions."

Two capabilities, both LLM-driven and both optional (config-gated so the
naive/improved comparison in Phase 5 can isolate their individual effect):

- `rewrite_query`: turns a terse or jargon-laden question into a fuller
  query closer to how the answer is likely phrased in the source
  documents. This is where "conversation-aware RAG" also plugs in — a
  follow-up question gets rewritten using prior turns BEFORE retrieval,
  so "what about for contractors?" retrieves against "leave policy for
  contractors" instead of retrieving nothing useful for four words.
- `expand_queries`: generates a small set of paraphrased variants of the
  same question for multi-query retrieval — each variant is retrieved
  independently and the results are merged, which helps when the
  "right" phrasing to match source text isn't obvious from the question
  alone.

Both fail open: if the LLM call errors, we fall back to the original
question rather than blocking retrieval on a transformation step failing.
"""

import logging

from app.generation.llm_client import LLMClient

logger = logging.getLogger("rag.retrieval.query_transform")

# The rewrite prompt is deliberately conservative. An earlier version said
# only "resolve it into a fully standalone question using that context",
# with no instruction to leave already-standalone questions alone. That
# caused a real bug: after a turn about the SmartHome Hub document, a new
# standalone question ("What was the PDF market share in 2020 according to
# the table?") got rewritten to "...in the SmartHome Hub document?" —
# injecting a topic that was never mentioned by the user, pointing
# retrieval at the wrong document, and causing a false abstention.
#
# The fix is threefold:
#   1. Explicit "return UNCHANGED if already standalone" rule — gives the
#      model permission to do nothing.
#   2. A counter-example showing this exact failure mode (standalone
#      question that appears after an unrelated prior turn).
#   3. "Do not append context just because it appeared earlier" — the
#      LLM's default bias is to include history whenever it's present.
#
# Retrieval also defends against imperfect rewrites: see improved_rag.py's
# OR-gate on raw vector relevance of the *original* question. Even if a
# rewrite goes wrong, retrieval still sees the user's actual question.
REWRITE_SYSTEM_PROMPT = """You rewrite user questions into clear, standalone search \
queries for a document retrieval system.

Your ONLY job is to resolve pronouns and implicit references in the user's \
NEW question so it makes sense without the conversation history.

Rules:
- If the user's new question is already standalone (no pronouns or implicit \
references that need resolution), return it UNCHANGED, exactly as written.
- Do NOT add topics, entities, document names, or constraints that are not \
clearly implied by pronouns or references in the new question itself.
- Do NOT append context from earlier turns just because it appeared earlier \
in the conversation. Prior topics are relevant ONLY if the new question \
directly refers back to them (e.g. "what about X", "and for Y", "that").
- Resolve pronouns (it / that / them / those) using the most recent relevant \
turn. Ignore everything else in the history.
- Expand obvious abbreviations/jargon only if it clearly helps matching source text.
- Do not answer the question. Output ONLY the rewritten query, nothing else.

Examples:

History: "How many days of paid annual leave do employees get?"
New question: "What about sick leave?"
Rewritten: What is the sick leave policy?

History: "What is the market size in the SmartHome Hub document?"
New question: "What was the PDF market share in 2020 according to the table?"
Rewritten: What was the PDF market share in 2020 according to the table?
(NOT rewritten — the new question is already standalone. The prior turn \
about SmartHome Hub is NOT relevant and must not be appended.)

History: "How many remote work days are allowed?"
New question: "And what about IT equipment?"
Rewritten: What is the IT equipment policy?

History: "What does the security FAQ say about MFA?"
New question: "What is control SEC-104 about?"
Rewritten: What is control SEC-104 about?
(NOT rewritten — standalone question, no pronoun or reference to resolve.)"""

MULTI_QUERY_SYSTEM_PROMPT = """You generate alternate phrasings of a search query to \
improve document retrieval recall. Given a question, output exactly 3 alternate \
phrasings, one per line, no numbering, no extra commentary. Each phrasing should \
target the same information need using different wording or angle."""


def rewrite_query(llm_client: LLMClient, question: str, history: str = "") -> str:
    if not history:
        return question

    user_prompt = f"Conversation history:\n{history}\n\nFollow-up question: {question}\n\nStandalone query:"
    try:
        rewritten = llm_client.generate(REWRITE_SYSTEM_PROMPT, user_prompt).strip()
        return rewritten or question
    except Exception as exc:  # noqa: BLE001 — never block retrieval on this
        logger.warning("query_rewrite_failed", extra={"error": str(exc)})
        return question


def expand_queries(llm_client: LLMClient, question: str, max_variants: int = 3) -> list[str]:
    try:
        raw = llm_client.generate(MULTI_QUERY_SYSTEM_PROMPT, question)
        variants = [line.strip("-• \t") for line in raw.splitlines() if line.strip()]
        return [question, *variants[:max_variants]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("query_expansion_failed", extra={"error": str(exc)})
        return [question]