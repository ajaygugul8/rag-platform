"""
Repeatable evaluation harness, per spec:
  "Provide a repeatable evaluation set containing questions, expected
   evidence and expected/acceptable answers."
  "An evaluation script can be run repeatedly and produces measurable
   retrieval and generation metrics."
  "A comparison of baseline RAG versus the improved pipeline using
   evaluation metrics."

What it does:
1. Ingests eval/sample_corpus/*.txt as fresh Documents tagged
   {"eval_corpus": true}, isolated from anything else in the DB via
   document_ids scoping â€” so this is safe to run against a demo instance
   that already has real uploaded documents.
2. Runs every question in golden_dataset.json through BOTH the naive and
   improved orchestrators (with a fake, deterministic-ish LLM client by
   default, so the retrieval metrics â€” the primary signal â€” don't depend
   on a paid API call; pass --real-llm to use the configured provider for
   answer-quality scoring too).
3. Computes, per pipeline:
     - hit_rate@k        â€” fraction of questions where the expected
                            source document appears anywhere in citations
     - mrr                â€” mean reciprocal rank of the expected source
                            document within citations
     - keyword_coverage   â€” fraction of expected_keywords found in the
                            generated answer (only meaningful with
                            --real-llm; with the fake client it measures
                            whether relevant text made it into context)
     - abstention_accuracy â€” fraction of expect_abstain questions where
                            the pipeline correctly abstained, and fraction
                            of answerable questions where it incorrectly
                            abstained (false abstention)
     - avg_latency_ms
4. Writes a timestamped JSON + Markdown report under eval/results/ and
   cleans up the eval corpus documents afterward (unless --keep-data).

Run from the repo root with the stack up:
    docker compose up -d postgres
    cd backend && pip install -r requirements.txt   # if not already
    cd ..
    python eval/run_eval.py
    python eval/run_eval.py --real-llm   # also scores answer quality via the real LLM
"""

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db.base import Base  # noqa: E402
from app.db.models import Document, DocumentStatus  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.generation.llm_client import LLMClient  # noqa: E402
from app.ingestion.pipeline import run_ingestion  # noqa: E402
from app.orchestrator import improved_rag, naive_rag  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "sample_corpus"
DATASET_PATH = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"


class FakeLLMClient(LLMClient):
    """Deterministic stand-in so retrieval metrics don't depend on API
    availability/cost. Echoes back the retrieved content so keyword
    coverage still measures something meaningful about what reached the
    prompt, without claiming to evaluate real generation quality."""

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return user_prompt


def ingest_corpus(db) -> list:
    documents = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        content = path.read_bytes()
        document = Document(
            filename=path.name,
            content_type="text/plain",
            size_bytes=len(content),
            storage_path=str(path),
            status=DocumentStatus.UPLOADED,
            doc_metadata={"eval_corpus": True},
        )
        db.add(document)
        db.flush()
        run_ingestion(db, document)
        db.refresh(document)
        documents.append(document)
    return documents


def cleanup_corpus(db, documents) -> None:
    for doc in documents:
        db.delete(doc)
    db.commit()


def _rank_of_expected(citations, expected_filename: str | None) -> int | None:
    if expected_filename is None:
        return None
    for i, c in enumerate(citations, start=1):
        if c.filename == expected_filename:
            return i
    return None


def _keyword_coverage(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in answer_lower)
    return hits / len(keywords)


def run_pipeline(pipeline_name: str, db, document_ids, dataset: list[dict], llm_client: LLMClient) -> dict:
    per_question = []

    for item in dataset:
        start = time.perf_counter()

        if pipeline_name == "baseline":
            result = naive_rag.answer_query(db, item["question"], document_ids=document_ids, llm_client=llm_client)
        else:
            result = improved_rag.answer_query(
                db, item["question"], document_ids=document_ids, llm_client=llm_client
            )

        latency_ms = (time.perf_counter() - start) * 1000
        rank = _rank_of_expected(result.citations, item["expected_source_file"])

        per_question.append(
            {
                "id": item["id"],
                "question": item["question"],
                "expect_abstain": item["expect_abstain"],
                "abstained": result.abstained,
                "correct_abstention_behavior": result.abstained == item["expect_abstain"],
                "expected_source_file": item["expected_source_file"],
                "citation_rank": rank,
                "hit": rank is not None or (item["expected_source_file"] is None and result.abstained),
                "reciprocal_rank": (1 / rank) if rank else 0.0,
                "keyword_coverage": _keyword_coverage(result.answer, item["expected_keywords"]),
                "latency_ms": round(latency_ms, 1),
            }
        )

    answerable = [q for q in per_question if not q["expect_abstain"]]

    return {
        "pipeline": pipeline_name,
        "hit_rate": mean(q["hit"] for q in answerable) if answerable else None,
        "mrr": mean(q["reciprocal_rank"] for q in answerable) if answerable else None,
        "keyword_coverage": mean(q["keyword_coverage"] for q in answerable) if answerable else None,
        "abstention_accuracy": mean(q["correct_abstention_behavior"] for q in per_question),
        "avg_latency_ms": round(mean(q["latency_ms"] for q in per_question), 1),
        "per_question": per_question,
    }


def render_markdown(results: list[dict]) -> str:
    lines = ["# RAG Evaluation Report", ""]
    lines.append("| Pipeline | Hit Rate | MRR | Keyword Coverage | Abstention Accuracy | Avg Latency (ms) |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r['pipeline']} | {r['hit_rate']:.2f} | {r['mrr']:.2f} | "
            f"{r['keyword_coverage']:.2f} | {r['abstention_accuracy']:.2f} | {r['avg_latency_ms']} |"
        )
    lines.append("")
    for r in results:
        lines.append(f"## {r['pipeline']} â€” per-question detail")
        lines.append("| ID | Hit | Rank | Keyword Cov. | Abstained (expected) |")
        lines.append("|---|---|---|---|---|")
        for q in r["per_question"]:
            lines.append(
                f"| {q['id']} | {'âœ…' if q['hit'] else 'âŒ'} | {q['citation_rank'] or '-'} | "
                f"{q['keyword_coverage']:.2f} | {q['abstained']} ({q['expect_abstain']}) |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run the RAG evaluation harness.")
    parser.add_argument("--real-llm", action="store_true", help="Use the configured real LLM instead of the fake echo client.")
    parser.add_argument("--keep-data", action="store_true", help="Don't delete the eval corpus documents afterward.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    llm_client: LLMClient
    if args.real_llm:
        from app.generation.providers import get_llm_client

        llm_client = get_llm_client()
    else:
        llm_client = FakeLLMClient()

    dataset = json.loads(DATASET_PATH.read_text())

    db = SessionLocal()
    try:
        print(f"Ingesting {len(list(CORPUS_DIR.glob('*.txt')))} sample documents...")
        documents = ingest_corpus(db)
        failed = [d for d in documents if d.status == DocumentStatus.FAILED]
        if failed:
            print(f"WARNING: {len(failed)} document(s) failed ingestion: {[d.filename for d in failed]}")
        document_ids = [d.id for d in documents]

        results = []
        for pipeline_name in ["baseline", "improved"]:
            print(f"Running pipeline: {pipeline_name} ({len(dataset)} questions)...")
            results.append(run_pipeline(pipeline_name, db, document_ids, dataset, llm_client))

        RESULTS_DIR.mkdir(exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        json_path = RESULTS_DIR / f"report_{timestamp}.json"
        md_path = RESULTS_DIR / f"report_{timestamp}.md"

        json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        md_path.write_text(render_markdown(results), encoding="utf-8")

        print("\n=== Summary ===")
        for r in results:
            print(
                f"{r['pipeline']:>10}: hit_rate={r['hit_rate']:.2f} mrr={r['mrr']:.2f} "
                f"keyword_coverage={r['keyword_coverage']:.2f} "
                f"abstention_accuracy={r['abstention_accuracy']:.2f} "
                f"avg_latency_ms={r['avg_latency_ms']}"
            )
        print(f"\nFull report: {json_path}\n                {md_path}")

        if not args.keep_data:
            cleanup_corpus(db, documents)
    finally:
        db.close()


if __name__ == "__main__":
    main()

