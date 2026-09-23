"""
Exercises the query endpoint's `pipeline` selector end-to-end: same
uploaded document, same question, both `baseline` (vector-only) and
`improved` (hybrid + rerank) pipelines. This is the first point in the
build where baseline-vs-improved comparison is actually possible — the
spec's acceptance criteria and Phase 5 evaluation both depend on it.

Uses a fake LLM client (no API key needed) and skips reranking via
monkeypatch when the cross-encoder model isn't available offline, so this
test doesn't require network access to run — the rerank *codepath* is
covered separately by unit tests where it can be mocked cheaply.
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


def test_baseline_and_improved_pipelines_both_answer(client, auth_headers, monkeypatch):
    monkeypatch.setattr(naive_rag, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(improved_rag, "get_llm_client", lambda: FakeLLMClient())
    # Reranker needs a model download; skip it for this offline test and
    # exercise hybrid retrieval + fusion without the cross-encoder stage.
    monkeypatch.setattr(improved_rag.settings, "rerank_enabled", False)

    files = {
        "file": (
            "leave_policy_v2.txt",
            io.BytesIO(
                b"Leave Policy\n\nAll full-time employees accrue 20 days of paid "
                b"annual leave per year, credited monthly."
            ),
            "text/plain",
        )
    }
    upload_resp = client.post(
        "/documents", files=files, data={"metadata": '{"department": "hr"}'}, headers=auth_headers
    )
    assert upload_resp.status_code == 201
    document_id = upload_resp.json()["id"]
    assert _wait_for_ready(client, auth_headers, document_id) == "ready"

    for pipeline in ("baseline", "improved"):
        resp = client.post(
            "/query",
            json={"question": "How many paid leave days per year?", "pipeline": pipeline},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pipeline"] == pipeline
        assert body["abstained"] is False, f"{pipeline} pipeline abstained unexpectedly"
        assert len(body["citations"]) >= 1


def test_metadata_filter_excludes_non_matching_documents(client, auth_headers, monkeypatch):
    import uuid as _uuid
    monkeypatch.setattr(improved_rag, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(improved_rag.settings, "rerank_enabled", False)

    tag = _uuid.uuid4().hex[:8]

    files = {"file": ("eng_doc.txt", io.BytesIO(b"The deployment pipeline uses blue-green releases."), "text/plain")}
    upload_resp = client.post(
        "/documents",
        files=files,
        data={"metadata": f'{{"department": "engineering-{tag}"}}'},
        headers=auth_headers,
    )
    document_id = upload_resp.json()["id"]
    assert _wait_for_ready(client, auth_headers, document_id) == "ready"

    resp = client.post(
        "/query",
        json={
            "question": "How does the deployment pipeline work?",
            "pipeline": "improved",
            "filters": {"department": f"hr-{tag}"},   # unique; no doc can match
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["abstained"] is True
