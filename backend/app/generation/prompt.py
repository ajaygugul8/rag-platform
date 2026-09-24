"""
Prompt construction is its own module — not inlined in the orchestrator —
because this is the single highest-leverage place for prompt-engineering
iteration during evaluation (Phase 5). Changing how sources are formatted
or how abstention is worded should never require touching retrieval or
generation code.
"""

from app.retrieval.vector_store import RetrievedChunk

SYSTEM_PROMPT = """You are an internal knowledge assistant. Answer ONLY using the numbered \
sources provided below. Follow these rules strictly:

1. Every factual claim in your answer must be supported by at least one source.
2. Cite sources inline using the format [n], where n is the source number.
3. If the sources do not contain enough information to answer the question, \
respond exactly with: "I don't have enough information in the knowledge base to \
answer that." Do not guess or use outside knowledge.
4. Be concise and direct. Do not repeat the question.
5. Some sources are images. When a source contains both "Alternate text for this \
image:" and "This image depicts:", the alternate text is authoritative — it comes \
from the document's author. The "This image depicts:" description is machine-
generated and may be imprecise. Use the description only to supplement the \
alternate text, never to contradict it. If the two disagree, prefer the alternate text.
"""


def format_sources(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        location = f"p.{chunk.page_number}" if chunk.page_number else (chunk.section_title or "")
        header = f"[{i}] {chunk.filename}" + (f" ({location})" if location else "")
        lines.append(f"{header}\n{chunk.content}")
    return "\n\n".join(lines)


def build_user_prompt(question: str, chunks: list[RetrievedChunk], history: str = "") -> str:
    sources_block = format_sources(chunks)
    history_block = f"Conversation so far:\n{history}\n\n" if history else ""
    return (
        f"{history_block}"
        f"Sources:\n{sources_block}\n\n"
        f"Question: {question}\n\n"
        f"Answer (with inline [n] citations):"
    )
