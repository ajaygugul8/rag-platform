# High-Level Design — Modern RAG Platform

**Audience:** an engineer or agent picking up this codebase to continue
the build.
**Companion docs:** `LLD.md` (module-level detail, schemas, API contracts,
algorithms), `docs/ARCHITECTURE.md` (deeper module layout),
`docs/MEMORY.md` (war stories and gotchas), `README.md` (user-facing).
**Source spec:** `Modern_RAG_Demo_Project_Requirements.pdf`.

---

## 1. Purpose

An internal knowledge assistant: users upload documents (PDF/DOCX/TXT/MD),
ask natural-language questions, and get answers grounded in those
documents with traceable citations. The system demonstrates the full
modern-RAG stack — chunking strategies, hybrid retrieval, reranking,
query transformation, contextual compression, **multimodal ingestion
(text + tables + images)**, evaluation, and observability — and is built
so a baseline pipeline and an improved pipeline can be compared
head-to-head on the same evaluation set.

## 2. Goals / Non-Goals

**Goals**

- End-to-end pipeline: ingest → index → retrieve → generate → cite
- Two retrieval pipelines (naive baseline, hybrid+rerank improved) that
  can be A/B compared via one API parameter
- Every component swappable via config or interface (embedding provider,
  LLM provider, vector store access pattern) without touching callers
- Repeatable evaluation with quantitative metrics
- Structured logs / tracing on every pipeline stage, no secrets in logs
- Runs fully locally with zero required API keys for retrieval and image
  description; LLM generation is the one component needing a provider
  key, with a local fallback
- **Multimodal ingestion** — tables and images become first-class chunks
  that flow through the same retrieval pipeline as text

**Non-Goals (explicitly out of scope for this build)**

- Multi-tenant user accounts / per-user document ACLs (single shared
  bearer token — see LLD §7)
- Horizontal scaling of the backend or a real task queue (ingestion runs
  in-process via FastAPI `BackgroundTasks`)
- A production-grade frontend beyond the Streamlit demo app
- Elasticsearch/OpenSearch or a dedicated vector DB (Postgres + pgvector
  covers both roles for this scale)
- OCR for scanned PDFs
- Fine-tuned vision models

## 3. System Context
┌───────────┐ HTTP/JSON ┌─────────────────────────────┐
│ Client │ ───────────────────▶ │ FastAPI Backend │
│ (curl / │ ◀─────────────────── │ │
│ frontend)│ │ documents, query endpoints │
└───────────┘ └───────────────┬──────────────┘
│
┌───────────────────────────────┼───────────────────────┐
▼ ▼ ▼
┌─────────────────────┐ ┌──────────────────────┐ ┌──────────────────┐
│ Postgres + pgvector │ │ Embedding provider │ │ LLM provider │
│ ─ documents │ │ (local bge-small- │ │ (Gemini multi- │
│ ─ chunks │ │ en-v1.5, 384-dim) │ │ key, Ollama │
│ (+ modality) │ │ │ │ fallback) │
│ ─ conversation_turns│ └──────────────────────┘ └──────────────────┘
│ ─ feedback │ │
└─────────────────────┘ ▼
┌──────────────────────┐
│ Vision provider │
│ (moondream:1.8b via │
│ Ollama, local) │
└──────────────────────┘

text

The backend is the only stateful application service; Postgres is the
only datastore (relational metadata + vector index + full-text index all
in one engine). Embedding, LLM, and vision providers are accessed through
pluggable client interfaces.

## 4. High-Level Architecture
Upload ─▶ Validation ─▶ Storage ─▶ [background] Ingestion Pipeline
│
▼
Docling parse (PDF/DOCX) or plain read (TXT/MD)
│
┌───────────┼───────────┐
▼ ▼ ▼
text_units table_units picture_units
│ │ │
▼ ▼ ▼
chunker markdown vision desc
(recursive) (whole) + alt text
│ │ │
└───────────┴───────────┘
▼
embed all chunks (bge-small-en-v1.5)
▼
persist with modality field
▼
chunks table

Query ─▶ Orchestrator (baseline | improved)
│
┌───────┴────────┐
▼ ▼
Vector-only Hybrid (vector + keyword)
retrieval + modality boost
│ │
│ Rerank (reorders only)
│ │
│ Modality guarantee
│ │
│ [Compression]
│ │
└──────────┬──────────┘
▼
Prompt construction (grounded, citation-enforcing,
abstention rule, alt-text-authoritative rule)
▼
LLM generation
▼
Answer + citations (doc, page, section, score)

text

Every stage lives behind a narrow interface in its own package, so a
component can be replaced by changing one file and one config value:

| Concern | Package | Swap point |
|---|---|---|
| Parsing | `app/ingestion/parsers.py` | add a function + registry entry |
| Chunking | `app/ingestion/chunking.py` | `ChunkingStrategy` enum |
| Embeddings | `app/embeddings/` | `EMBEDDING_PROVIDER` env var |
| Vector store access | `app/retrieval/vector_store.py` | swap the query, not the caller |
| Keyword search | `app/retrieval/keyword_store.py` | swap the query, not the caller |
| Reranking | `app/retrieval/reranker.py` | replace the model |
| Generation | `app/generation/providers.py` | `LLM_PROVIDER` env var |
| Vision | `app/generation/vision.py` | `OLLAMA_VISION_MODEL` env var |
| Orchestration | `app/orchestrator/` | one module per pipeline variant |

## 5. Technology Decisions (and why)

| Layer | Choice | Rationale |
|---|---|---|
| Language / API | Python 3.12, FastAPI | async, typed, free OpenAPI docs |
| Vector store | Postgres + pgvector (HNSW index) | one database for metadata, vectors, and full-text — avoids running a second stateful service for this scale |
| Keyword search | Postgres full-text (`tsvector` + `ts_rank_cd`) | avoids standing up Elasticsearch for a demo; same lexical-matching value |
| Embeddings | `sentence-transformers` (`bge-small-en-v1.5`) local | runs with zero API keys; swappable via `EMBEDDING_PROVIDER` |
| Reranker | Local cross-encoder (`bge-reranker-base`) | same zero-dependency reasoning; reorders, never gates |
| LLM | Gemini (multi-key rotation) + Ollama fallback | free-tier primary with a local safety net; per-project quota means multiple keys help only across separate Google Cloud projects |
| Vision | `moondream:1.8b` via Ollama | local, free, 1.7 GB; ~5–15s per image on CPU |
| Multimodal parsing | Docling 2.14 (PDF/DOCX) | returns typed elements — `TextItem`, `SectionHeaderItem`, `ListItem`, `TableItem`, `PictureItem`. Replaces pypdf/python-docx. |
| Table serialization | Markdown | LLMs read markdown tables natively; CSV loses column alignment, HTML burns tokens |
| DOCX alt text | python-docx `wp:docPr` XML walk | `inline_shapes` misses floating images; walking raw XML catches all of them |
| Orchestration | Hand-rolled pipeline (no LangChain/LlamaIndex) | every stage (chunking, retrieval, rerank, compression, prompt build) must be visible, testable, and independently swappable |
| Frontend | Streamlit | spec's "simple web UI"; single-file, pure HTTP client against the backend |
| Migrations | Alembic, revisions 0001–0002 | 0002 added `modality` + `parent_chunk_id` for multimodal chunks |
| Deployment | Docker Compose | matches the spec's local-reproducibility requirement |

## 6. Key Design Decisions Worth Knowing Before Extending This

1. **Two orchestrators, not one with flags.** `naive_rag.py` (vector-only)
   and `improved_rag.py` (hybrid + rerank + compression + query rewriting
   + conversation) are separate modules on purpose — the spec's
   acceptance criteria require a baseline-vs-improved comparison, which
   needs two real implementations, not one implementation with a toggle
   that could drift into being "the same thing twice".

2. **Abstention is threshold-based per pipeline**, not a shared constant.
   Vector cosine similarity and cross-encoder scores are different
   scales, so each orchestrator has its own threshold tuned for what it
   actually measures.

3. **Ingestion failure never crashes the request.** Every stage in the
   ingestion pipeline is wrapped so a bad PDF/DOCX marks the `Document`
   row `FAILED` with a reason instead of raising past the API boundary.

4. **Metadata filtering is JSONB containment**, not a fixed filter
   schema — `doc_metadata` is a free-form JSON object per document, so
   new filterable fields never require a migration.

5. **Config is centralized in one file** (`app/config.py`); no other
   module reads `os.environ` directly. This is what makes "secrets never
   hard-coded" actually auditable.

6. **Tables are never split.** One table = one chunk, serialized to
   markdown. Splitting destroys row/column associations.

7. **Image alt text is authoritative over vision descriptions.** Prompt
   rule 5 enforces this at generation time.

8. **Modality boost + guarantee + gate relaxation.** Three additive
   retrieval fixes that close the "text query → image answer" gap.

9. **Image chunks are structurally identifiable** by their content
   prefix (`"Alternate text for this image"` / `"This image depicts"`).
   Retrieval code uses this instead of a schema field on
   `RetrievedChunk`.

10. **`LLMClient` interface is frozen.** Both orchestrators call it in
    multiple places. Extending it breaks every call site silently.

11. **Alembic, not `create_all()`.** `create_all()` only adds new tables;
    it silently does nothing when an existing table needs a new column.
    That caused a real production-adjacent crash.

12. **Frontend is a pure HTTP client.** `frontend/app.py` never imports
    `app.*`. Any HTTP client can replace it without backend changes.

## 7. Implementation Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: repo, config, Docker, DB, upload endpoint, auth, health check | ✅ Built, tested |
| 2 | Baseline RAG: parsing, cleaning, chunking, embeddings, vector retrieval, generation, naive orchestrator | ✅ Built, tested |
| 3 | Retrieval upgrades: metadata filtering, hybrid (vector+keyword) search, reranking, pipeline comparison endpoint | ✅ Built, fully verified end-to-end |
| 4 | Advanced RAG: query rewriting, multi-query expansion, contextual compression, conversation-aware retrieval | ✅ Built, verified |
| 5 | Evaluation: golden dataset + harness comparing baseline vs. improved | ✅ Done. `improved` scored hit_rate 0.83 vs. baseline 0.50, MRR 0.83 vs. 0.50, keyword_coverage 0.75 vs. 0.50, abstention_accuracy 0.86 vs. 0.57 — at a latency cost of ~1050ms vs. ~65ms average. Full report in `eval/results/`. |
| 6 | Production hardening: tracing, caching, Alembic, feedback, LLM providers | ⚠️ Partial — done: Alembic (0001, 0002), feedback endpoint, Gemini multi-key + Ollama fallback, per-stage tracing, token-usage logging, retrieval-result logging. Deferred: Redis cache, task queue, per-user auth. |
| 7 | Demo packaging + multimodal: Docling, tables, images, frontend, docs | ✅ Done — text + tables + images all chunked and retrievable through the same pipeline. Streamlit frontend with citations, feedback, session history. |

**Verification status:** all 18 functional requirements from the spec are
met; all 7 acceptance criteria pass; all 7 demo scenarios from spec §12
verified; 23 automated tests pass.

## 8. Bugs Found and Fixed During Verification

Worth recording here since they'll recur if anyone rebuilds these pieces
without knowing why they're written this way:

- **"Cannot copy out of meta tensor; no data!"** — thrown by both the
  local embedding model (`app/embeddings/local.py`) and the local
  reranker (`app/retrieval/reranker.py`) on ingestion/query. Root cause:
  newer `transformers`/`accelerate` versions default to loading model
  weights via a "meta device" placeholder that's only safely materialized
  if the model download completed cleanly. Fixed in both files by forcing
  `device="cpu"` and disabling `low_cpu_mem_usage`. Also added a
  persistent `hf_cache` Docker volume so the model only needs to download
  once.

- **Rerank threshold vetoed correct matches.** An earlier `>= 0.15`
  filter on cross-encoder output silently dropped a correctly-ranked
  vocabulary-mismatched match that scored 0.0056. Fixed by removing the
  filter — reranking reorders, never gates.

- **LLM-abstention flag was wrong.** Both orchestrators hardcoded
  `abstained=False` on the final return even when the LLM echoed the
  abstention message. Fixed by reconciling the flag with the LLM output.

- **Query rewrite over-eagerness.** Rewriting was injecting context from
  prior turns into standalone questions. Fixed by a "return UNCHANGED if
  already standalone" prompt rule plus an OR-gate on the original
  question's raw relevance.

- **Metadata filter leaked through raw-relevance gate.** `_retrieve` and
  the safety net called `vector_search` without `metadata_filters`. Fixed
  by passing them.

- **DOCX alt text wasn't extracted.** Docling doesn't populate
  `caption_text` for DOCX; python-docx's `inline_shapes` misses floating
  images. Fixed by walking `wp:docPr` XML elements in the document body.

- **Modality gap dropped image chunks.** "Chart" queries returned text
  chunks *about* charts, not the actual chart image chunk. Fixed by a
  modality boost in `hybrid_search`, a modality guarantee after rerank,
  and a modality-aware relaxation of the abstention gate.

- **moondream mislabeled a chart.** moondream:1.8b called a "screen
  reader market share" pie chart "operating systems used by various
  companies." Fixed by prompt rule 5 — document-supplied alt text is
  authoritative over machine-generated descriptions.

## 9. Open Items / Known Gaps

**Functional gaps: none.** Every requirement in the source spec is met.
The items below are documented limitations or explicitly out-of-scope.

### Multimodal limitations
- **Vision descriptions are non-authoritative.** `moondream:1.8b` is a
  small model — it correctly identifies images but can mislabel their
  subject. Where the document supplies alt text, that text wins (prompt
  rule 5). Without alt text, the description is the only signal and
  errors propagate. Upgrade path: `qwen2.5-vl:7b` via Ollama (4.7 GB,
  ~30–60s/image on CPU).
- **PDF images are not always classified as PictureItems.** The 50-page
  sample PDF yielded 0 PictureItems despite containing charts. This is a
  Docling layout-model behavior, not a bug. Fallback (render pages as
  images) is not implemented.
- **Text adjacent to an image is sometimes absorbed into the picture
  region** by Docling's layout model. One paragraph in `sample3.docx`
  was affected.
- **Image descriptions add ~5–15s per image at ingestion.** Acceptable
  for demo-scale corpora; would need a queue or GPU for hundreds of
  documents.

### Other limitations
- **Auth is one shared bearer token** — no per-user documents or access
  control. First thing to replace for real multi-user use.
- **Cache is not thread-safe.** `core/cache.py` is an in-process LRU+TTL.
  Must be replaced with Redis before running `--workers > 1`.
- **Ingestion runs via FastAPI `BackgroundTasks`** (in-process,
  single-worker). Swap for a real queue (Celery/RQ/arq) before scaling
  ingestion independently of the API.
- **Multi-query preserves jargon** rather than bridging to corpus
  vocabulary. The LLM bridges residual gaps at generation time.
- **No load testing / latency benchmarking** has been done at any phase.

## 10. How to Verify the Current State Yourself

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health

# Backend unit tests — expected: 23 passed
cd backend && pip install -r requirements.txt
pytest -v

# Evaluation harness
cd ..
python eval/run_eval.py

