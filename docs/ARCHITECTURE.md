## `docs/ARCHITECTURE.md`

Save at `docs/ARCHITECTURE.md`.

```markdown
# Architecture — Modern RAG Platform

**Companion docs:** `../HLD.md` (decisions & phase status),
`../LLD.md` (module detail, schemas, API contracts),
`PRD.md` (requirements), `DESIGN.md` (deep design), `RULES.md` (invariants).

---

## 1. System Context

```
┌────────────────┐      HTTP/JSON       ┌──────────────────────────────┐
│  Browser       │ ───────────────────▶ │     Frontend (Streamlit)      │
│  (user)        │ ◀─────────────────── │     port 8501                 │
└────────────────┘                      └──────────────┬───────────────┘
                                                       │ HTTP/JSON
                                                       ▼
                                        ┌──────────────────────────────┐
                                        │    Backend (FastAPI)          │
                                        │    port 8000                  │
                                        │  /documents  /query /feedback │
                                        │  /health                      │
                                        └──────────────┬───────────────┘
                                                       │
                  ┌────────────────────────────────────┼────────────────────────────┐
                  ▼                                    ▼                            ▼
        ┌──────────────────────┐         ┌─────────────────────────┐   ┌───────────────────────┐
        │ Postgres + pgvector  │         │  Embedding provider     │   │    LLM provider       │
        │ ─ documents          │         │  (local bge-small-en-   │   │  Gemini (multi-key)   │
        │ ─ chunks (vec + tsv) │         │   v1.5, 384-dim, CPU)   │   │   ↓ fallback          │
        │ ─ conversation_turns │         │                         │   │  Ollama (local)       │
        │ ─ feedback           │         └─────────────────────────┘   └───────────────────────┘
        └──────────────────────┘
```

**Stateful services:** exactly one — Postgres. It holds metadata, vectors,
full-text index, conversation history, and feedback. There is no separate
vector DB, no Elasticsearch, no Redis (yet), no object store (the
filesystem is the swap point for S3/GCS).

**External calls:** embeddings and reranker are **local** (no network at
query time). The LLM is the only networked component, and it has a local
fallback. This is a deliberate design choice — a demo that works offline
except for one provider is far easier to reason about than one with three.

---

## 2. Repository Layout

```
rag-platform/
├── docker-compose.yml          postgres + backend + frontend
├── .env / .env.example         single source of config
├── HLD.md / LLD.md / README.md
├── docs/                       PRD, ARCHITECTURE, RULES, DESIGN, TASKS, MEMORY
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── app/
│   │   ├── main.py                    FastAPI app, lifespan, middleware, exception handler
│   │   ├── config.py                  the ONLY module that reads os.environ
│   │   ├── api/
│   │   │   ├── documents.py           POST/GET /documents
│   │   │   ├── query.py               POST /query
│   │   │   ├── feedback.py            POST /feedback
│   │   │   └── schemas.py             Pydantic request/response models
│   │   ├── core/
│   │   │   ├── exceptions.py          RagPlatformError hierarchy
│   │   │   ├── security.py            bearer-token dependency
│   │   │   └── cache.py               in-process TTL/LRU (not thread-safe)
│   │   ├── db/
│   │   │   ├── base.py, session.py, models.py, init.sql
│   │   ├── ingestion/
│   │   │   ├── validation.py, storage.py, parsers.py, cleaning.py,
│   │   │   ├── chunking.py, pipeline.py
│   │   ├── embeddings/
│   │   │   ├── base.py, local.py, openai_provider.py, provider.py
│   │   ├── retrieval/
│   │   │   ├── vector_store.py, keyword_store.py, hybrid.py,
│   │   │   ├── metadata.py, reranker.py, query_transform.py, compression.py
│   │   ├── generation/
│   │   │   ├── llm_client.py, providers.py, prompt.py
│   │   ├── orchestrator/
│   │   │   ├── naive_rag.py           baseline pipeline
│   │   │   └── improved_rag.py        hybrid + rerank + compression + rewrite + multi-query
│   │   ├── conversation/
│   │   │   └── history.py
│   │   └── observability/
│   │       ├── logging.py, tracing.py
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   └── app.py                         Streamlit UI (pure HTTP client)
└── eval/
    ├── run_eval.py                    Phase 5 harness
    ├── regenerate_report.py           re-render markdown from JSON
    ├── golden_dataset.json
    ├── sample_corpus/*.txt
    └── results/
```

---

## 3. Ingestion Pipeline

```
Upload (multipart/form-data)
   │
   ▼
validation.py ─── reject bad MIME, bad size ─── 422
   │
   ▼
storage.py ────── write to UPLOAD_DIR, create documents row (status=UPLOADED)
   │
   ▼  (BackgroundTask — response already returned to client)
   │
   ▼
parsers.py ────── PDF (page-aware), DOCX (heading-aware), TXT, MD → (text, metadata)
   │
   ▼
cleaning.py ───── normalize whitespace, preserve headings/structure
   │
   ▼
chunking.py ───── fixed OR recursive (structure-aware)
   │
   ▼
embeddings/local.py ── bge-small-en-v1.5 → 384-dim vectors
   │
   ▼
persist ────────── chunks rows: content, chunk_index, page_number,
                   section_title, token_count, chunk_metadata, embedding,
                   content_tsv (generated), document_id
   │
   ▼
documents.status = READY   (or FAILED + failure_reason on any error)
```

**Key invariants:**
- Every stage is wrapped so a bad file marks the document `FAILED` with
  a reason, never raises past the API boundary.
- `chunks.document_id` has `ON DELETE CASCADE` — deleting a document
  deletes its chunks.
- `content_tsv` is a **persisted generated column** — Postgres maintains
  it automatically; the app never writes to it.

**Parser notes (verified against real documents):**
- **PDF:** pdfplumber-based. Page numbers extracted correctly. Section
  titles are *not* extracted (PDF has no heading structure the way DOCX
  does). Tables are extracted as flattened text — usable for retrieval,
  not for structured table access. 10-page and 50-page PDFs both
  processed successfully.
- **DOCX:** heading-aware. Populates `section_title` (`Leave Policy`,
  `Sick Leave`, etc.) — this is what makes DOCX citations look better
  than PDF citations.
- **TXT / MD:** plain text. No section structure.

---

## 4. Query Pipeline — Two Orchestrators

### 4.1 Baseline (`naive_rag.py`)

```
embed(question)
   │
   ▼
vector_search(top_k=RETRIEVAL_TOP_K)
   │
   ▼
filter: score >= MIN_RELEVANCE_SCORE (0.6, raw cosine)
   │
   ├─ empty → abstain (no LLM call)
   │
   ▼
build grounded prompt → llm.generate() → answer + citations
```

Fast (65 ms warm). Vector-only retrieval. This is the pipeline the demo
compares against.

### 4.2 Improved (`improved_rag.py`)

```
[history] ── if session_id: get_recent_history()
   │
   ▼
[rewrite] ── if history: rewrite_query()
   │            Rule: return UNCHANGED if the new question is standalone.
   │            Resolves pronouns only; does not inject prior topics.
   │
   ▼
[retrieval] ── if ENABLE_MULTI_QUERY: expand_queries() → up to 3 paraphrases
   │            each paraphrase → hybrid_search()
   │            merge: keep best score per chunk_id
   │
   ▼
[relevance gate] ── max( raw_vector_relevance of resolved_query,
   │                      raw_vector_relevance of original question,
   │                      keyword_ts_rank > 0 )
   │
   ├─ empty OR below 0.6 → abstain
   │
   ▼
[rerank] ── cross-encoder rerank, top_n = RERANK_TOP_N
   │          REORDERS; does NOT filter — cross-encoder scores are
   │          not calibrated 0–1 (see DESIGN.md §5)
   ▼
[compression] ── dedupe + greedy select within CONTEXT_TOKEN_BUDGET
   │
   ├─ empty → abstain
   │
   ▼
build grounded prompt (with history) → llm.generate() → persist turns
   │
   ▼
answer + citations (abstained flag reconciled with LLM output)
```

**Asymmetry to remember:** baseline abstains at one point (after vector
filter). Improved abstains at **two** points (after retrieval, after
compression). Reading improved logs, "abstained" does not necessarily mean
"retrieval found nothing".

**Why the improved pipeline is 16× slower:**
- Rewrite (when history exists): 1 LLM call
- Multi-query (when enabled): 1 LLM call
- Generation: 1 LLM call
- Hybrid retrieval: two queries (vector + keyword) per paraphrase
- Reranker: cross-encoder inference over ~24 candidates
- Compression: dedup + budget selection

The baseline does exactly one embedding + one vector search + one LLM call.

---

## 5. Retrieval Subsystem

### 5.1 Hybrid Fusion (`retrieval/hybrid.py`)

- `candidate_k = top_k * candidate_multiplier` (default 3).
- Runs vector search and keyword search independently.
- **Min-max normalizes** each score set before fusion. Why: cosine and
  `ts_rank_cd` are on incomparable scales.
- `combined = alpha * v_norm + (1 - alpha) * k_norm`, `alpha = HYBRID_ALPHA` (0.5).

**Important property:** min-max normalization guarantees the *best*
candidate is near 1.0 **even when the whole batch is irrelevant**. This is
why the fused score is unsuitable as an abstention gate — see §5.6.

### 5.2 Keyword Search (`retrieval/keyword_store.py`)

Postgres full-text — `content_tsv` (generated column) with `ts_rank_cd`.
GIN index `ix_chunks_content_tsv`. Chosen over Elasticsearch because it
delivers the same lexical-matching value at this scale with zero extra
infrastructure.

### 5.3 Metadata Filter (`retrieval/metadata.py`)

`build_metadata_filter({"department":"hr"})` compiles to a JSONB
containment check on `doc_metadata`. Multiple keys are ANDed. **No
migration is needed when new filterable fields appear.**

### 5.4 Reranker (`retrieval/reranker.py`)

`BAAI/bge-reranker-base` cross-encoder, lazily loaded once per process
(`@lru_cache`), **forced to CPU with `low_cpu_mem_usage=False`** (see
RULES.md §2.1 — this is not removable).

Scores **replace** the chunk's prior score entirely; they are not blended
with hybrid score.

### 5.5 Vector Search (`retrieval/vector_store.py`)

pgvector HNSW index (`vector_cosine_ops`), created at app startup (its
DDL is not expressible through SQLAlchemy's `Index()`). Cosine distance.
`EMBEDDING_DIM` (384) is baked into the column type; changing the model
requires re-ingestion.

### 5.6 Why abstention gates on raw cosine, not fused/reranked score

Three score types exist in the pipeline. Only one is safe to gate on:

| Score | Range | Property | Gate-safe? |
|---|---|---|---|
| Raw vector cosine | [0, 1] absolute | calibrated similarity | ✅ |
| Hybrid fused | [0, 1] per-query | min-max normalized | ❌ always tops out near 1.0 |
| Cross-encoder | unbounded | not calibrated | ❌ correct match can score 0.005 |

The pipeline gates abstention on **raw cosine of the resolved question**
(max across the original question and any paraphrases). Empirically
calibrated: relevant questions score ~0.84, off-topic ~0.38–0.50.
Threshold: 0.6.

---

## 6. Generation Subsystem

- **`llm_client.py`** defines `LLMClient` with a single method:
  `generate(system: str, user: str) -> str`.
- **`providers.py`** returns the concrete client based on `LLM_PROVIDER`:
  - `GeminiClient` — multi-key rotation with per-key cooldown on 429
  - `OllamaClient` — OpenAI-compatible local endpoint
  - `FallbackLLMClient` — tries primary, falls back on any exception
  - `get_llm_client()` — factory that dispatches on `LLM_PROVIDER`
- **`prompt.py`** holds `SYSTEM_PROMPT` and `build_user_prompt()`. The
  system prompt enforces: (a) answer only from retrieved context,
  (b) cite sources, (c) abstain if the context is insufficient.

**Hard rule:** the `LLMClient` interface does not change. Both
orchestrators call it in two places each (rewriting + final answer).
Extending it silently breaks four call sites.

---

## 7. Frontend (Streamlit)

`frontend/app.py` is a **pure HTTP client** — it never touches Postgres.
Four sections:

| Tab | Action | Backend call |
|---|---|---|
| **Chat** | ask a question | `POST /query` with `session_id` |
| **Upload** | upload a file, poll for ready | `POST /documents`, `GET /documents/{id}` |
| **Documents** | list everything ingested | `GET /documents` |
| **Settings** | pipeline toggle, API token | — |

Session state (`st.session_state.session_id`) persists a UUID across
Streamlit reruns, so follow-up questions work. `New conversation` resets it.

Feedback: 👍/👎 buttons per answer, wired to `POST /feedback`.

---

## 8. Persistence Layer

Single Postgres instance. Four tables:

| Table | Role | Notes |
|---|---|---|
| `documents` | Uploaded file metadata + ingestion status | `doc_metadata` JSONB for free-form filtering |
| `chunks` | Text + embedding + generated tsvector + chunk metadata | HNSW index on `embedding`; GIN on `content_tsv` |
| `conversation_turns` | Short-term conversation history | Keyed by client-generated `session_id` |
| `feedback` | Useful/not-useful + optional comment | Written by `POST /feedback` |

**Schema management:** Alembic. Revision `0001` is the baseline (current
schema). Future changes: edit `app/db/models.py` → `alembic revision
--autogenerate -m "..."` → review → `alembic upgrade head`.

**Enum casing gotcha:** `DocumentStatus` enum values are stored
**uppercase** in Postgres (`READY`, `FAILED`) even though Python defines
them lowercase. Any raw SQL must use uppercase labels.

---

## 9. Deployment

`docker-compose.yml`:

- **`postgres`** — `pgvector/pgvector:pg16`, healthchecked via `pg_isready`.
  Host port **5433** (moved off 5432 to avoid a collision with a native
  Windows Postgres install — see MEMORY.md).
- **`backend`** — FastAPI + uvicorn, depends on `postgres` healthy.
  Env overrides `DATABASE_URL` to use the `postgres` service name instead
  of `localhost`, so both host-side tools and container processes work off
  the same `.env`.
- **`frontend`** — Streamlit, talks to `http://backend:8000` by service name.

Volumes:
- `pgdata` — database
- `upload_data` — uploaded files
- `hf_cache` — HuggingFace model cache (critical; keeps embedding +
  reranker models from re-downloading on every container recreate)

---

## 10. Extension Points

| Concern | Package | How to swap |
|---|---|---|
| Parser | `ingestion/parsers.py` | add function + registry entry |
| Chunking | `ingestion/chunking.py` | new `ChunkingStrategy` enum value |
| Embeddings | `embeddings/` | `EMBEDDING_PROVIDER` (and update `EMBEDDING_DIM`!) |
| Vector search | `retrieval/vector_store.py` | swap the query, not the caller |
| Keyword search | `retrieval/keyword_store.py` | swap the query, not the caller |
| Reranker | `retrieval/reranker.py` | replace the model; keep the `(query, chunks, top_n)` signature |
| LLM | `generation/providers.py` | `LLM_PROVIDER`; **do not change `LLMClient`** |
| Orchestration | `orchestrator/` | add a module; expose via `pipeline` enum |
| Frontend | `frontend/app.py` | any HTTP client works; the API is the boundary |

---

## 11. Trade-Offs (documented deliberately)

- **Hand-rolled pipeline, no LangChain/LlamaIndex.** Every stage must be
  visible, testable, and independently swappable. Frameworks tend to
  obscure that, which defeats the point of the demo.
- **Two orchestrators, not one with flags.** The spec requires a
  baseline-vs-improved comparison. That needs two real implementations,
  not a toggle that can drift into being "the same thing twice".
- **Postgres does three jobs.** One stateful service to run, back up,
  and reason about. At demo scale, the operational win beats the
  theoretical benefit of a dedicated vector DB.
- **Local embeddings + local reranker.** Zero required API keys for the
  retrieval half. Only generation touches the network — and it has a
  local fallback.
- **Streamlit, not React.** The spec asks for "a simple web UI".
  Streamlit delivers it in one file, and the backend API is the same
  either way.
```

---

**2 of 6 delivered.** Reply **"next"** for `RULES.md`.