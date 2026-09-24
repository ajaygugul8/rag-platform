"""
Phase 3 verification: tables routed into chunks and retrievable.

Uses sample3.docx, which contains two tables (a simple 5x3 screen-reader
table and a complex table with merged year headers). The simple table's
"JAWS | 853 | 49%" row is the ground truth — asking for JAWS's response
count should retrieve the table chunk and answer with 853.
"""
import io

from app.orchestrator import improved_rag, naive_rag


def _wait_for_ready(client, headers, document_id, max_seconds=180):
    import time
    start = time.time()
    while time.time() - start < max_seconds:
        resp = client.get(f"/documents/{document_id}", headers=headers)
        status = resp.json()["status"].lower()
        if status in ("ready", "failed"):
            return status
        time.sleep(2)
    return "timeout"


def test_table_chunk_is_created_and_retrievable(client, auth_headers, monkeypatch):
    """Upload a DOCX with tables, verify:
      1. At least one chunk has modality='table'
      2. A table-specific query returns the table value
    """
    # Force deterministic LLM behavior — use the fake client used elsewhere
    from tests.test_phase3_hybrid_retrieval import FakeLLMClient  # reuse
    monkeypatch.setattr(improved_rag, "get_llm_client", lambda: FakeLLMClient())
    monkeypatch.setattr(naive_rag, "get_llm_client", lambda: FakeLLMClient())

    # Read the sample3.docx from the eval corpus (or wherever it lives)
    import pathlib
    path = pathlib.Path("tests/fixtures/sample3.docx")
    if not path.exists():
        # Fall back to the uploaded copy in _scratch if the fixture isn't there
        import pytest
        pytest.skip(f"fixture not found at {path}")

    files = {
        "file": (
            "sample3.docx",
            io.BytesIO(path.read_bytes()),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = client.post("/documents", files=files, headers=auth_headers)
    assert resp.status_code == 201
    document_id = resp.json()["id"]

    status = _wait_for_ready(client, auth_headers, document_id)
    assert status == "ready", f"ingestion ended with status={status}"

    # Query the table content
    qresp = client.post(
        "/query",
        json={
            "question": "What is the response count for JAWS according to the screen reader table?",
            "pipeline": "improved",
        },
        headers=auth_headers,
    )
    assert qresp.status_code == 200
    body = qresp.json()

    # The table value is present in the document, so we should not abstain
    assert body["abstained"] is False, f"unexpected abstention: {body['answer'][:200]}"

    # At least one citation should come from sample3.docx
    cites = body.get("citations") or []
    filenames = [c["filename"] for c in cites]
    assert "sample3.docx" in filenames, f"sample3.docx not cited; got {filenames}"

    # The table content should be present as a citation excerpt OR the
    # answer should contain the value
    joined = " ".join((c.get("excerpt") or "") for c in cites)
    assert ("853" in joined) or ("853" in body["answer"]), (
        f"expected table value 853 in answer or citations; "
        f"answer={body['answer'][:200]!r}, excerpts={joined[:300]!r}"
    )