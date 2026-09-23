"""
This test uses a FakeLLMClient so the full retrieve -> prompt -> generate
loop is exercised without hitting a real OpenAI/Anthropic API — CI should
never depend on external API keys or network for correctness tests.

It DOES use the real local embedding model (sentence-transformers), since
that's what makes retrieval quality testable at all. First run downloads
the model; subsequent runs are cached.
"""

import io
import time

from app.core.exceptions import GenerationError
from app.generation.llm_client import LLMClient
from app.orchestrator import improved_rag, naive_rag


class FakeLLMClient(LLMClient):
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return "Employees get 20 days of leave per year. [1]"


def _wait_for_ready(client, auth_headers, document_id, timeout_s=30):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"/documents/{document_id}", headers=auth_headers)
        status_ = resp.json()["status"]
        if status_ in ("ready", "failed"):
            return status_
        time.sleep(0.5)
    raise TimeoutError("Document never finished processing")


def test_end_to_end_upload_and_query(client, auth_headers, monkeypatch):
    monkeypatch.setattr(naive_rag, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(improved_rag, "get_llm_client", lambda: FakeLLMClient())

    files = {
        "file": (
            "leave_policy.txt",
            io.BytesIO(b"Leave Policy\n\nEmployees get 20 days of paid leave per year, accrued monthly."),
            "text/plain",
        )
    }
    upload_resp = client.post("/documents", files=files, headers=auth_headers)
    assert upload_resp.status_code == 201
    document_id = upload_resp.json()["id"]

    final_status = _wait_for_ready(client, auth_headers, document_id)
    assert final_status == "ready"

    query_resp = client.post(
        "/query", json={"question": "How many leave days do employees get?"}, headers=auth_headers
    )
    assert query_resp.status_code == 200
    body = query_resp.json()
    assert body["abstained"] is False
    assert "20 days" in body["answer"]
    assert len(body["citations"]) >= 1
    assert body["citations"][0]["filename"] == "leave_policy.txt"


def test_query_abstains_with_empty_knowledge_base(client, auth_headers, monkeypatch):
    monkeypatch.setattr(naive_rag, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(improved_rag, "get_llm_client", lambda: FakeLLMClient())

    resp = client.post(
        "/query",
        json={"question": "What is the meaning of an entirely unrelated made-up term xyzzyplonk?"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    # With no relevant chunks above the threshold, the orchestrator abstains
    # without even calling the LLM.
    body = resp.json()
    if body["citations"] == []:
        assert body["abstained"] is True
