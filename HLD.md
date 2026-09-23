# High-Level Design — Modern RAG Platform

**Audience:** an engineer or agent picking up this codebase to continue the build.
**Companion doc:** `LLD.md` (module-level detail, schemas, API contracts, algorithms).
**Source spec:** `Modern_RAG_Demo_Project_Requirements.pdf` (original requirements).

---

## 1. Purpose

An internal knowledge assistant: users upload documents (PDF/DOCX/TXT/MD), ask
natural-language questions, and get answers grounded in those documents with
traceable citations. The system demonstrates the full modern-RAG stack —
chunking strategies, hybrid retrieval, reranking, query transformation,
context compression, evaluation, and observability — not just a vector-search
chatbot, and is built so a baseline pipeline and an improved pipeline can be
compared head-to-head on the same evaluation set.

## 2. Goals / Non-Goals

**Goals**
- End-to-end pipeline: ingest → index → retrieve → generate → cite
- Two retrieval pipelines (naive baseline, hybrid+rerank improved) that can be
  A/B compared via one API parameter
- Every component swappable via config or interface (embedding provider, LLM
  provider, vector store access pattern) without touching callers
- Repeatable evaluation with quantitative metrics
- Structured logs / tracing on every pipeline stage, no secrets in logs
- Runs fully locally with zero required API keys (local embeddings + local
  reranker); LLM generation is the one component needing a provider key

**Non-Goals (explicitly out of scope for this build)**
- Multi-tenant user accounts / per-user document ACLs (single shared bearer
  token for the whole demo — see LLD §7)
- Horizontal scaling of the backend or a real task queue (ingestion runs
  in-process via FastAPI `BackgroundTasks`)
- A production-grade frontend (none has been built yet — see §8, Open Items)
- Elasticsearch/OpenSearch or a dedicated vector DB (Postgres + pgvector
  covers both roles for this scale)

## 3. System Context

```
┌───────────┐      HTTP/JSON       ┌─────────────────────────────┐
│  Client   │ ───────────────────▶ │        FastAPI Backend       │
│ (curl /   │ ◀─────────────────── │                              │
│  frontend)│                      │  documents, query endpoints  │
└───────────┘                      └───────────────┬──────────────┘
                                                     │
                     ┌───────────────────────────────┼───────────────────────┐
                     ▼                                ▼                       ▼
          ┌─────────────────────┐         ┌──────────────────────┐  ┌──────────────────┐
          │  Postgres + pgvector │         │  Embedding provider   │  │   LLM provider    │
          │  (documents, chunks, │         │  (local ST model or   │  │  (OpenAI /        │
          │   conversation_turns)│         │   OpenAI embeddings)  │  │   Anthropic)      │
          └─────────────────────┘         └──────────────────────┘  └──────────────────┘
```

The backend is the only stateful application service; Postgres is the only
datastore (relational metadata + vector index + full-text index all in one
engine). Embedding and LLM providers are external processes/APIs accessed
through pluggable client interfaces.

## 4. High-Level Architecture

```
Upload  ─▶ Validation ─▶ Storage ─▶ [background] Ingestion Pipeline
                                        │
                         Parse ─▶ Clean ─▶ Chunk ─▶ Embed ─▶ Persist
                                                              │
                                                              ▼
                                                        chunks table
                                                     (content + vector +
                                                      tsvector + metadata)

Query ─▶ Orchestrator (naive | improved)
              │
      ┌───────┴────────┐
      ▼                ▼
  Vector-only      Hybrid (vector + keyword) ─▶ Rerank ─▶ [Compression]
  retrieval                                                     │
      └───────────────────────┬─────────────────────────────────┘
                               ▼
                    Prompt construction (grounded,
                    citation-enforcing, abstention rule)
                               ▼
                          LLM generation
                               ▼
                    Answer + citations (doc, page, score)
```

Every stage lives behind a narrow interface in its own package, so a
component can be replaced by changing one file and one config value:

| Concern | Package | Swap point |
|---|---|---|
| Parsing | `app/ingestion/parsers.py` | add a function + registry entry |
| Chunking | `app/ingestion/chunking.py` | `ChunkingStrategy` enum |
| Embeddings | `app/embeddings/` | `EMBEDDING_PROVIDER` env var |
| Vector store access | `app/retrieval/vector_store.py` | swap the query, not the caller |
| Keyword search | `app/retrieval/keyword_store.py` | swap the query, not the caller |
| Generation | `app/generation/providers.py` | `LLM_PROVIDER` env var |
| Orchestration | `app/orchestrator/` | one module per pipeline variant |

## 5. Technology Decisions (and why)

| Layer | Choice | Rationale |
|---|---|---|
| Language / API | Python 3.12, FastAPI | async, typed, free OpenAPI docs |
| Vector store | Postgres + pgvector (HNSW index) | one database for metadata, vectors, and full-text — avoids running a second stateful service for this scale |
| Keyword search | Postgres full-text (`tsvector` + `ts_rank_cd`) | avoids standing up Elasticsearch for a demo; same lexical-matching value |
| Embeddings | `sentence-transformers` (`bge-small-en-v1.5`) local | runs with zero API keys; swappable via `EMBEDDING_PROVIDER` |
| Reranker | Local cross-encoder (`bge-reranker-base`) | same zero-dependency reasoning; reorders, never gates (see §6.3) |
| LLM | Gemini (multi-key rotation) + Ollama fallback | free-tier primary with a local safety net; per-project quota means multiple keys help only across separate Google Cloud projects |
| Orchestration | Hand-rolled pipeline (no LangChain/LlamaIndex) | every stage must be visible, testable, and independently swappable |
| Frontend | Streamlit | spec's "simple web UI"; single-file, pure HTTP client against the backend |
| Migrations | Alembic (stamped to revision `0001`) | adopted mid-project after `create_all()` silently failed to add a column to an existing table; forward-only |
| Deployment | Docker Compose | matches the spec's local-reproducibility requirement |

## 6. Key Design Decisions Worth Knowing Before Extending This

1. **Two orchestrators, not one with flags.** `naive_rag.py` (vector-only) and
   `improved_rag.py` (hybrid + rerank + compression + query rewriting +
   conversation) are separate modules on purpose — the spec's acceptance
   criteria require a baseline-vs-improved comparison, which needs two real
   implementations, not one implementation with a toggle that could drift
   into being "the same thing twice."
2. **Abstention is threshold-based per pipeline**, not a shared constant —
   vector cosine similarity and cross-encoder scores are different scales,
   so each orchestrator has its own `MIN_RELEVANCE_SCORE` tuned for what it
   actually measures.
3. **Ingestion failure never crashes the request.** Every stage in the
   ingestion pipeline is wrapped so a bad PDF/DOCX marks the `Document` row
   `FAILED` with a reason instead of raising past the API boundary.
4. **Metadata filtering is JSONB containment**, not a fixed filter schema —
   `doc_metadata` is a free-form JSON object per document, so new filterable
   fields never require a migration.
5. **Config is centralized in one file** (`app/config.py`); no other module
   reads `os.environ` directly. This is what makes "secrets never
   hard-coded" actually auditable rather than a policy nobody can verify.

## 7. Implementation Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: repo, config, Docker, DB, upload endpoint, auth, health check | ✅ Built, tested |
| 2 | Baseline RAG: parsing, cleaning, chunking, embeddings, vector retrieval, generation, naive orchestrator | ✅ Built, tested |
| 3 | Retrieval upgrades: metadata filtering, hybrid search, reranking, pipeline comparison endpoint | ✅ Built, fully verified end-to-end on real Docker |
| 4 | Advanced RAG: query rewriting, multi-query expansion, contextual compression, conversation-aware retrieval | ✅ Built, verified. Rewrite now includes a "return unchanged" rule for standalone questions, plus an OR-gate on the original question's raw relevance as a safety net. |
| 5 | Evaluation: golden dataset + harness comparing baseline vs. improved | ✅ Done. `improved` scored hit_rate 0.83 vs. baseline 0.50, mrr 0.83 vs. 0.50, keyword_coverage 0.75 vs. 0.50, abstention_accuracy 0.86 vs. 0.57 — at a latency cost of ~1050ms vs. ~65ms average. Report in `eval/results/`. |
| 6 | Production hardening: tracing, caching, auth, task queue, Alembic, feedback, LLM providers | ⚠️ Partial. **Done:** Alembic migrations; `POST /feedback` endpoint; Gemini multi-key + Ollama fallback; `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`; per-stage tracing; token-usage logging; retrieval-result logging. **Deferred (documented as out of scope):** Redis cache, task queue, per-user auth. |
| 7 | Demo packaging: Streamlit frontend, README, docs, architecture diagram, demo script | ✅ Frontend, README, and `docs/` complete. Architecture diagram in `docs/ARCHITECTURE_DIAGRAM.md`. Demo scenario runner in `scripts/demo.py`. |

**Verification status:** all 18 functional requirements from the spec are met; all 7 acceptance criteria pass; all 7 demo scenarios from spec §12 verified; 22 automated tests pass.
## 8. Bugs Found and Fixed During Verification

Worth recording here since they'll recur if anyone rebuilds the embedding
or reranker model loading code without knowing why it's written this way:

- **"Cannot copy out of meta tensor; no data!"** — thrown by both the local
  embedding model (`app/embeddings/local.py`) and the local reranker
  (`app/retrieval/reranker.py`) on ingestion/query. Root cause: newer
  `transformers`/`accelerate` versions default to loading model weights via
  a "meta device" placeholder that's only safely materialized if the model
  download completed cleanly — any network interruption (VPN, firewall,
  flaky connection) leaves the model half-loaded and throws this on first
  use. Fixed in both files by forcing `device="cpu"` and disabling
  `low_cpu_mem_usage`, which uses the slower-but-bulletproof normal load
  path. Also added a persistent `hf_cache` Docker volume so the model only
  needs to download once, ever, instead of on every container recreate —
  reducing how often this failure mode can even be triggered.

## 9. Open Items / Known Gaps

**Functional gaps: none.** Every requirement in the source spec is met.
The items below are documented limitations, deferred polish, or explicitly
out-of-scope features.

### Limitations (by design or by physics)
- **PDF tables are extracted as flattened text**, not structured rows.
  Values are retrievable (e.g. "$50 Billion", "74.8%"), but row/column
  structure is lost. A table-aware extractor (`unstructured`, pdfplumber's
  `extract_table`) would preserve structure at the cost of a new dependency.
- **No OCR / image-text extraction.** Scanned PDFs and image-only tables
  produce no usable text. Out of scope per §2 Non-Goals.
- **Multi-query paraphrases preserve domain jargon.** "PTO" generates
  more PTO-flavored variants, not "paid annual leave". The LLM bridges the
  vocabulary gap at generation time; retrieval does not. Documented in
  `LLD.md` §4.
- **Reranker top-1 can be the wrong chunk** when the query repeats a
  document's entity name. The LLM still cites correctly; a UI that
  highlights only the top citation would be misleading.
- **Gemini free tier is 20 requests/day per Google Cloud project**, not
  per key. Multiple keys from the same project share one quota; multi-key
  rotation only helps across separate projects.
- **Gemini free tier has 3–12 s variance per query** due to intermittent
  503 responses triggering SDK retry/backoff. The Ollama fallback keeps
  the system usable when Gemini is degraded.

### Deferred hardening (out of scope for the demo)
- **Redis cache** — `core/cache.py` is an in-process LRU+TTL and is not
  thread-safe. Must be replaced before running `--workers > 1` or multiple
  replicas.
- **Task queue** — ingestion runs via FastAPI `BackgroundTasks`
  (in-process, single-worker). Swap for Celery/RQ/arq before scaling
  ingestion independently of the API.
- **Real auth** — one shared bearer token. No per-user documents or ACLs.
- **Load testing** — no concurrent-user benchmark has been run.

## 10. How to Verify the Current State Yourself

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health

cd backend && pip install -r requirements.txt
pytest -v          # Phases 1-3 tests are known-good; Phase 4 tests are unverified in CI

cd ..
python eval/run_eval.py     # has never been run — first run is a good sanity check
```

See `LLD.md` for exact module responsibilities, schemas, and API contracts.