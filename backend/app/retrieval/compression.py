"""
Contextual compression, per spec: "Remove duplicates and compress/select
the most relevant context within the LLM context budget."

Two passes, both cheap (no extra LLM calls — this runs after reranking,
right before prompt construction, and shouldn't become the slowest part
of the pipeline):

1. Deduplication — chunking with overlap (Phase 2) means adjacent chunks
   from the same document often share a large fraction of their text.
   Hybrid retrieval can also surface the same chunk twice in different
   candidate pools before hybrid.py's own id-based merge (which only
   catches exact chunk_id matches, not near-duplicate text from a
   *different* chunk). Near-duplicates are removed here using word-shingle
   *containment* similarity, keeping whichever copy scored higher.

2. Budget selection — greedily keep the highest-scored, deduplicated
   chunks until the running token count would exceed `token_budget`. This
   is a token *count* budget, not a sentence-extraction summarizer —
   trimming whole chunks preserves coherence (a half-sentence of context
   is often worse than one fewer full chunk).

Why containment, not Jaccard: an earlier version used Jaccard on 5-word
shingles at threshold 0.8. That could not catch the case it was written
for — true Jaccard between a chunk and its suffix is capped at
|shorter| / |longer|, which for realistic near-duplicates stays below
0.8. Containment (|A∩B| / min(|A|,|B|)) handles the "one chunk is
essentially a subset of another" pattern correctly. A length-ratio guard
prevents a tiny heading-only chunk from being flagged as a duplicate of
a large chunk that happens to contain its words.
"""

from app.ingestion.chunking import approx_token_count
from app.retrieval.vector_store import RetrievedChunk

DEFAULT_TOKEN_BUDGET = 2000
DEDUP_CONTAINMENT_THRESHOLD = 0.8
DEDUP_MAX_LENGTH_RATIO = 2.0


def _shingle_set(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = text.lower().split()
    if len(words) < n:
        return {tuple(words)}
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _containment(a: set, b: set) -> float:
    """|A ∩ B| / min(|A|, |B|). Empty input → 0.0."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _is_near_duplicate(a: set, b: set) -> bool:
    """True if `a` and `b` are near-duplicates by containment, subject to
    a length-ratio guard so a short heading is never flagged as a
    duplicate of a long chunk that merely contains its words."""
    if not a or not b:
        return False
    ratio = max(len(a), len(b)) / min(len(a), len(b))
    if ratio > DEDUP_MAX_LENGTH_RATIO:
        return False
    return _containment(a, b) >= DEDUP_CONTAINMENT_THRESHOLD


def deduplicate(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Assumes `chunks` is already sorted best-first (as rerank()/hybrid_search()
    return it) so the first copy of a near-duplicate we keep is the
    highest-scored one."""
    kept: list[RetrievedChunk] = []
    kept_shingles: list[set] = []

    for chunk in chunks:
        shingles = _shingle_set(chunk.content)
        if any(_is_near_duplicate(shingles, existing) for existing in kept_shingles):
            continue
        kept.append(chunk)
        kept_shingles.append(shingles)

    return kept


def select_within_budget(
    chunks: list[RetrievedChunk], token_budget: int = DEFAULT_TOKEN_BUDGET
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    used_tokens = 0

    for chunk in chunks:
        chunk_tokens = approx_token_count(chunk.content)
        if used_tokens + chunk_tokens > token_budget and selected:
            # Keep going past a single oversized chunk only if we have
            # nothing yet — better to answer from one big chunk than abstain.
            continue
        selected.append(chunk)
        used_tokens += chunk_tokens

    return selected


def compress_context(
    chunks: list[RetrievedChunk], token_budget: int = DEFAULT_TOKEN_BUDGET
) -> list[RetrievedChunk]:
    return select_within_budget(deduplicate(chunks), token_budget)