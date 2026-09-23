from app.generation.llm_client import LLMClient
from app.retrieval.compression import deduplicate, select_within_budget
from app.retrieval.query_transform import rewrite_query
from app.retrieval.vector_store import RetrievedChunk
import uuid


def _chunk(text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="doc.txt",
        content=text,
        page_number=1,
        section_title=None,
        score=score,
    )


def test_deduplicate_removes_near_identical_chunks():
    base = "Employees are entitled to twenty days of paid annual leave per calendar year."
    near_dup = base + " Extra sentence that barely changes the chunk."
    chunks = [_chunk(base, 0.9), _chunk(near_dup, 0.8), _chunk("Totally unrelated content about parking.", 0.7)]

    deduped = deduplicate(chunks)

    assert len(deduped) == 2
    assert deduped[0].score == 0.9  # higher-scored copy kept


def test_select_within_budget_always_keeps_at_least_one_chunk():
    huge_chunk = _chunk("word " * 5000, 0.9)
    selected = select_within_budget([huge_chunk], token_budget=10)
    assert len(selected) == 1  # never abstain just because one chunk is big


def test_select_within_budget_stops_adding_once_full():
    chunks = [_chunk("word " * 100, 0.9), _chunk("word " * 100, 0.8), _chunk("word " * 100, 0.7)]
    selected = select_within_budget(chunks, token_budget=150)
    assert 1 <= len(selected) < 3


class EchoLLMClient(LLMClient):
    """Returns a fixed rewritten query so the test doesn't need a real API key."""

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return "What is the leave policy for contractors?"


def test_rewrite_query_uses_history_when_present():
    client = EchoLLMClient()
    result = rewrite_query(client, "what about for contractors?", history="user: what is the leave policy?")
    assert "contractors" in result.lower()


def test_rewrite_query_skips_llm_without_history():
    class ExplodingLLMClient(LLMClient):
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            raise AssertionError("should not be called when there's no history")

    result = rewrite_query(ExplodingLLMClient(), "what is the leave policy?", history="")
    assert result == "what is the leave policy?"
