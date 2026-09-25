Here's the corrected `LLD.md`. Three fixes applied: (1) §9 next-steps list no longer says "expand from 7 to 20" (it's already 20), (2) malformed markdown structure unwrapped — the file was pasted with extra code-fence wrapping, (3) added a "Current eval results" reference in §8 so the numbers live in this doc too. Everything else preserved.

Save at repo root as `LLD.md`.

```markdown
# Low-Level Design - Modern RAG Platform

**Companion doc:** `HLD.md` (architecture, decisions, phase status).
Read that first if you haven't - this doc assumes you know the system
layout.

---

## 1. Repository Layout

```
rag-platform/
├── docker-compose.yml
├── .env.example
├── HLD.md / LLD.md / README.md
├── docs/                              # PRD, ARCHITECTURE, RULES, DESIGN, TASKS, MEMORY
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_add_chunk_modality.py
│   ├── app/
│   │   ├── main.py                    FastAPI app, lifespan, middleware, exception handlers
│   │   ├── config.py                  Settings - the ONLY place os.environ is read
│   │   ├── api/
│   │   │   ├── documents.py           POST/GET /documents
│   │   │   ├── query.py               POST /query
│   │   │   ├── feedback.py            POST /feedback
│   │   │   └── schemas.py             Pydantic request/response models
│   │   ├── core/
│   │   │   ├── exceptions.py          Domain exception hierarchy
│   │   │   ├── security.py            Bearer-token auth dependency (HTTPBearer)
│   │   │   └── cache.py               In-process TTL/LRU cache
│   │   ├── db/
│   │   │   ├── base.py, session.py, models.py, init.sql
│   │   ├── ingestion/
│   │   │   ├── validation.py          MIME type + size checks
│   │   │   ├── storage.py             Write uploads to disk
│   │   │   ├── parsers.py             Docling for PDF/DOCX; plain read for TXT/MD
│   │   │   ├── cleaning.py            Whitespace normalization
│   │   │   ├── chunking.py            Fixed + recursive text; whole-table markdown
│   │   │   └── pipeline.py            Orchestration, per-modality routing
│   │   ├── embeddings/
│   │   │   ├── base.py, local.py, openai_provider.py, provider.py
│   │   ├── retrieval/
│   │   │   ├── vector_store.py        pgvector HNSW cosine search
│   │   │   ├── keyword_store.py       Postgres full-text ts_rank_cd
│   │   │   ├── hybrid.py              Min-max fusion + modality boost
│   │   │   ├── metadata.py            JSONB containment filter
│   │   │   ├── reranker.py            bge-reranker-base cross-encoder
│   │   │   ├── query_transform.py     rewrite_query + expand_queries
│   │   │   └── compression.py         Containment dedup + budget selection
│   │   ├── generation/
│   │   │   ├── llm_client.py          Frozen LLMClient interface
│   │   │   ├── providers.py           OpenAI-compatible client + fallback chain
│   │   │   ├── prompt.py              SYSTEM_PROMPT (5 rules) + user prompt builder
│   │   │   └── vision.py              moondream image description
│   │   ├── orchestrator/
│   │   │   ├── naive_rag.py           Baseline pipeline
│   │   │   └── improved_rag.py        Hybrid + rerank + compression + rewrite
│   │   ├── conversation/
│   │   │   └── history.py             get_recent_history + add_turn
│   │   └── observability/
│   │       ├── logging.py             JSON formatter config
│   │       └── tracing.py             trace_stage context manager
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   └── app.py                         Streamlit UI (pure HTTP client)
└── eval/
    ├── run_eval.py                    Phase 5 harness
    ├── regenerate_report.py           Re-render markdown from JSON
    ├── golden_dataset.json
    ├── sample_corpus/
    └── results/
```

## 2. Data Model

### `documents`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `filename` | varchar(512) | |
| `content_type` | varchar(128) | must be one of 4 allowed MIME types |
| `size_bytes` | int | |
| `storage_path` | varchar(1024) | local filesystem path; swap point for S3/GCS |
| `status` | enum: `UPLOADED, PROCESSING, READY, FAILED` | stored **uppercase** in Postgres |
| `failure_reason` | text, nullable | set only when `status = FAILED` |
| `doc_metadata` | JSONB | free-form filterable metadata |
| `created_at`, `updated_at` | timestamptz | |

### `chunks`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK -> documents, `ON DELETE CASCADE` | |
| `content` | text | the chunk's actual text |
| `chunk_index` | int | order within document |
| `page_number` | int, nullable | from PDF parsing |
| `section_title` | varchar(512), nullable | from heading detection |
| `token_count` | int | approximate (word-count x 1.3) |
| `modality` | varchar(16) | `'text'` / `'table'` / `'image'`; default `'text'` |
| `parent_chunk_id` | UUID, nullable, self-FK | links image/table chunks back to surrounding text |
| `chunk_metadata` | JSONB | e.g. `{"chunking_strategy": "recursive", "image_path": "..."}` |
| `embedding` | `vector(384)` | pgvector; nullable until ingestion completes |
| `content_tsv` | `tsvector`, **generated column** (`to_tsvector('english', content)`, persisted) | Postgres maintains automatically |
| `created_at` | timestamptz | |

Indexes:
- `ix_chunks_document_id` (btree)
- `ix_chunks_content_tsv` (GIN)
- `ix_chunks_modality` (btree)
- `ix_chunks_embedding_hnsw` (HNSW, `vector_cosine_ops` - created at app startup)

### `conversation_turns`
`id, session_id (client-generated), role ("user"|"assistant"), content, created_at`.
Indexed on `(session_id, created_at)`.

### `feedback`
`id, query, answer, is_useful (bool), comment (nullable), created_at`.

## 3. API Contract

### `POST /documents`
Auth: `Authorization: Bearer <API_AUTH_TOKEN>` (required on all routes).

Request: `multipart/form-data`
- `file`: the document (pdf/docx/txt/md, <= `MAX_UPLOAD_MB`)
- `metadata`: form field, JSON object string, default `"{}"`

Response `201`:
```json
{
  "id": "uuid", "filename": "policy.pdf", "content_type": "application/pdf",
  "size_bytes": 12345, "status": "uploaded", "failure_reason": null,
  "doc_metadata": {"department": "hr"}, "created_at": "2026-..."
}
```

Errors: `422` (bad file type/size, or `metadata` not valid JSON), `401`
(missing/bad token).

Ingestion runs as a `BackgroundTask` after the response is sent - the
client must poll `GET /documents/{id}` until `status` is `READY` or
`FAILED` before querying.

### `GET /documents`, `GET /documents/{id}`
List / fetch a single document. `404` if not found.

### `POST /query`
Request:
```json
{
  "question": "string, required",
  "pipeline": "baseline" | "improved",
  "document_ids": ["uuid", "..."] | null,
  "filters": {"department": "hr"} | null,
  "session_id": "string" | null
}
```

Response `200`:
```json
{
  "answer": "string",
  "abstained": false,
  "pipeline": "improved",
  "resolved_query": "string | null",
  "citations": [
    {"document_id": "uuid", "filename": "policy.pdf", "page_number": 3,
     "section_title": null, "score": 0.81, "excerpt": "first 280 chars..."}
  ]
}
```

Caching: if `session_id` is `None`, the response is looked up/stored in
`app/core/cache.py`'s `query_cache` keyed on `(pipeline, question,
document_ids, filters)`.

### `POST /feedback`
Request:
```json
{"query": "...", "answer": "...", "is_useful": true, "comment": null}
```
Response `201`: `{"id": "uuid", "created_at": "..."}`

### `GET /health`
Returns `{"status": "ok", "app_env": ..., "database": "ok" | "unreachable"}`. Never raises.

## 4. Orchestrator Internals

### `naive_rag.answer_query(db, question, document_ids=None, llm_client=None)`
1. Embed `question` - wrapped in `trace_stage("embed_query")`
2. `vector_search(db, embedding, top_k=RETRIEVAL_TOP_K)` - wrapped in `trace_stage("vector_search")`
3. Filter to `score >= MIN_RELEVANCE_SCORE` (0.6, raw cosine)
4. If none pass -> abstain, no LLM call
5. Else build prompt and call `llm_client.generate(...)` - wrapped in `trace_stage("generate")`
6. Reconcile the `abstained` flag with the LLM output

### `improved_rag.answer_query(db, question, document_ids=None, metadata_filters=None, session_id=None, llm_client=None)`
1. **History**: if `session_id`, pull last `CONVERSATION_HISTORY_TURNS` turns - `trace_stage("history_lookup")`
2. **Query rewrite**: if history non-empty - `trace_stage("rewrite_query")`
3. **Retrieval**: multi-query expansion + hybrid search per variant - `trace_stage("retrieve")`
4. If no candidates -> abstain
5. **Safety net**: if `resolved_query != question`, compute raw relevance on original too - `trace_stage("rewrite_safety_net")`
6. **Gate**: abstain if below threshold (0.6 normally, 0.35 for image queries with an image candidate)
7. **Rerank**: cross-encoder rescoring - `trace_stage("rerank")`
8. **Modality guarantee**: splice best image candidate back if it got dropped
9. **Compress**: dedupe + budget - `trace_stage("compress")`
10. If empty -> abstain
11. **Generate** - `trace_stage("generate")`
12. Reconcile the `abstained` flag with the LLM output

**Important asymmetry:** `naive_rag` abstains once, right after retrieval.
`improved_rag` abstains three times - after retrieval, after compression,
and after generation. "Abstained" in the improved pipeline does not
necessarily mean "retrieval found nothing."

## 5. Retrieval Algorithms

### Hybrid fusion (`retrieval/hybrid.py`)
```
candidate_k = top_k * candidate_multiplier   # default 3
vector_results  = vector_search(candidate_k)
keyword_results = keyword_search(candidate_k)

v_norm = min_max_normalize({chunk_id: score for vector_results})
k_norm = min_max_normalize({chunk_id: score for keyword_results})

for each chunk_id in (v_norm union k_norm):
    combined_score = alpha * v_norm.get(id, 0) + (1-alpha) * k_norm.get(id, 0)

# Modality boost (before sorting)
if query contains image keyword:
    for chunk in blended:
        if chunk.content starts with image-chunk prefix:
            score *= 2.5

return top_k by combined_score, descending
```

`alpha` = `HYBRID_ALPHA` (default 0.5). `min_max_normalize` maps an empty
dict to `{}`, and an all-equal-scores dict to all `1.0` (avoids
div-by-zero, treats ties as maximally relevant rather than arbitrarily
zero).

**Why min-max and not raw scores:** cosine similarity and `ts_rank_cd`
live on incomparable numeric scales - combining raw values would let
whichever score happens to have a larger typical range dominate
regardless of `alpha`.

**Why min-max makes the fused score unsuitable as an abstention gate:**
normalization guarantees the top candidate is near 1.0 even when the
entire candidate set is irrelevant. Abstention gates on raw cosine
instead.

### Metadata filter (`retrieval/metadata.py`)
`build_metadata_filter({"department": "hr"})` compiles to a JSONB
containment check - the filter dict must be a subset of `doc_metadata`.
Multiple filter keys are ANDed by JSONB containment semantics
automatically.

### Reranking (`retrieval/reranker.py`)
`CrossEncoder("BAAI/bge-reranker-base").predict([(query, chunk.content), ...])`,
lazily loaded once per process (`@lru_cache`), forced to `device="cpu"`
with `low_cpu_mem_usage=False` (see section 6.6).

Scores **replace** the chunk's existing `.score` entirely (not blended
with the hybrid score). The hybrid score picked the candidate pool; the
cross-encoder score orders the final answer's citations.

**Critical:** `bge-reranker-base` scores are **not calibrated 0-1**. A
correctly-ranked vocabulary-mismatched match can score 0.0056. Reranking
**reorders, never gates.**

### Chunking (`ingestion/chunking.py`)
- **Fixed**: sliding window over `text.split()` by word count, `step = chunk_size - overlap`
- **Recursive**: split on `\n\n` paragraph boundaries; accumulate into a
  buffer until exceeding `chunk_size`, then flush; single oversized
  paragraph falls back to fixed-size
- **Tables**: one chunk per table, markdown, never split
- Token counting is **approximate**: `word_count * 1.3`, not a real
  tokenizer

### Modality detection
Retrieval code does not have a `modality` field on `RetrievedChunk`.
Image chunks are structurally identifiable by their content prefix:

```python
_IMAGE_CHUNK_PREFIXES = ("Alternate text for this image", "This image depicts")
is_image = chunk.content.startswith(_IMAGE_CHUNK_PREFIXES)
```

## 6. Cross-Cutting Concerns

### 6.1 Validation (`ingestion/validation.py`)
Allowed `content_type` -> extension map: PDF, DOCX, `text/plain`,
`text/markdown`. Size checked against `MAX_UPLOAD_MB` before anything
touches disk or the DB.

### 6.2 Auth (`core/security.py`)
Single shared bearer token compared to `API_AUTH_TOKEN`. Uses FastAPI's
`HTTPBearer` security scheme so the `/docs` "Authorize" button appears
and Swagger UI attaches the Authorization header automatically.

### 6.3 Exceptions (`core/exceptions.py`)
`RagPlatformError` is the base; `main.py` has a single handler that
converts any subclass into a clean `400` JSON body. `IngestionError`
carries a `document_id` so the pipeline can mark the specific document
`FAILED` without crashing the background task.

### 6.4 Logging & Tracing
`observability/logging.py` configures a JSON formatter on the root
logger - every `logger.info(..., extra={...})` becomes one JSON line
with those extra fields merged in. Convention (not enforced in code):
never put file contents, request bodies, or API keys in `extra=`.

`observability/tracing.py` wraps a block in
`with trace_stage("name", **fields):` and emits `stage_started` /
`stage_completed` / `stage_failed` log lines with a `span_id` and
duration. Every orchestrator stage is wrapped individually.

### 6.5 Token usage logging
Both Gemini and Ollama responses expose token counts
(`prompt_tokens`, `completion_tokens`, `total_tokens`). `providers.py`
logs these as `llm_usage` events after every successful call. Silent
no-op if the provider doesn't expose them.

### 6.6 Local model loading - the meta-tensor pitfall
Both `embeddings/local.py`'s `_load_model()` and
`retrieval/reranker.py`'s `_load_reranker()` explicitly pass
`device="cpu"` and disable `low_cpu_mem_usage`. Without this, newer
`transformers`/`accelerate` versions load weights via a "meta device"
that only resolves correctly if the download completes without
interruption - any network hiccup leaves the model half-materialized and
throws `NotImplementedError: Cannot copy out of meta tensor; no data!`
on first use. **Do not remove these kwargs.**

`docker-compose.yml` mounts a named `hf_cache` volume to
`/root/.cache/huggingface` in the backend service specifically so this
download only ever has to succeed once.

Docling also uses HuggingFace to fetch its layout models. On the first
parse, the offline flags must be temporarily disabled so Docling can
download. After the first parse, models live in the volume and the
offline flags prevent unnecessary network checks.

### 6.7 Caching
`core/cache.py`'s `TTLCache` is a plain `OrderedDict`-based LRU+TTL
cache, **not thread-safe and not shared across processes**. Repeated
stateless queries hit the cache; session-scoped queries always bypass it
(conversation state can change the resolved query between calls).
Replace with Redis before running `--workers > 1`.

## 7. Configuration Reference

All in `app/config.py`, loaded from `.env`:

```
APP_ENV=local                LOG_LEVEL=INFO
MAX_UPLOAD_MB=25             UPLOAD_DIR=./data/uploads
DATABASE_URL=postgresql+psycopg://postgres:<pwd>@localhost:5433/modern_rag

EMBEDDING_PROVIDER=local     EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384

LLM_PROVIDER=gemini_with_ollama_fallback
GEMINI_API_KEYS=key1,key2,key3
GEMINI_MODEL=gemini-2.5-flash
OLLAMA_MODEL=qwen3:8b
OLLAMA_HOST=http://host.docker.internal:11434

VISION_ENABLED=true
OLLAMA_VISION_MODEL=moondream:1.8b
VISION_MAX_TOKENS=60

RETRIEVAL_TOP_K=8            HYBRID_ALPHA=0.5
RERANK_ENABLED=true          RERANK_TOP_N=4
ENABLE_MULTI_QUERY=false     CONTEXT_TOKEN_BUDGET=2000
CONVERSATION_HISTORY_TURNS=6

API_AUTH_TOKEN=change-me-dev-token
```

**Hard constraint:** `EMBEDDING_DIM` must match what `EMBEDDING_MODEL`
actually produces. Mismatched dimensions fail at ingestion (pgvector
rejects the insert), but rows from an old model become unusable and need
re-ingestion.

## 8. Test Coverage Map

| File | Covers | DB needed? | External deps? |
|---|---|---|---|
| `test_documents.py` | upload validation, auth, CRUD, health | yes | no |
| `test_chunking.py` | fixed/recursive chunking (pure functions) | no | no |
| `test_hybrid.py` | score normalization, metadata filter clause construction (pure functions) | no | no |
| `test_phase3_hybrid_retrieval.py` | baseline vs. improved comparison, metadata-filter-driven abstention | yes | local embedding model |
| `test_phase3b_tables.py` | table chunks retrievable | yes | local embedding model |
| `test_phase4_advanced.py` | dedup (containment), budget selection, rewrite fallback logic | no | no |
| `test_query_e2e.py` | full upload -> ingest -> query flow | yes | local embedding model |

**23 tests passing.** Run inside the container:

```bash
docker compose exec backend pytest -v
```

(Host-side pytest is blocked by Windows Application Control on
`_argkmin.pyd`, a scikit-learn dependency pulled in transitively by
Docling. The container is Linux and has no such policy.)

**Not covered by automated tests:** reranker correctness under pytest,
multi-query expansion, cache under concurrent requests, the eval harness
itself, tracing output correctness.

### Current eval results (20-question golden set)

| Metric | baseline | improved | delta |
|---|---:|---:|---:|
| hit_rate | 0.83 | **0.94** | +0.11 |
| MRR | 0.81 | **0.94** | +0.13 |
| keyword_coverage | 0.81 | **0.89** | +0.08 |
| abstention_accuracy | 0.85 | **0.95** | +0.10 |
| avg_latency_ms | **71.4** | 1698.5 | +1627 |

Full report: `eval/results/report_<timestamp>.json` and `.md`.

**Manually verified end-to-end (via live Docker deployment):**
- Multi-document, multi-format retrieval (PDF + DOCX + TXT) with correct
  source routing and correct abstention
- DOCX section-title extraction
- Reranking producing sensible relevance ordering
- Conversation-aware query rewriting via `resolved_query`
- Response caching (stateless hits, session-scoped bypasses)
- Table extraction with merged cells preserving structure
- Image description + alt-text retrieval (via `sample3.docx`)
- Modality boost firing (`"image_boost": true` in logs)

## 9. Suggested Next Steps for Whoever Picks This Up

1. **Re-run the eval harness after any pipeline change** and compare the
   new metrics against the baseline numbers in section 8. The 20-question
   golden set is stable; treat the metrics as a regression suite.
2. **Try `qwen2.5-vl:7b` instead of `moondream:1.8b`** for more accurate
   image descriptions. Change `OLLAMA_VISION_MODEL` in `.env` and
   re-ingest. Expected: better chart comprehension, ~4x slower per image
   on CPU.
3. **Deploy to Oracle Cloud free ARM** (12 GB RAM - the only free
   platform that runs the full stack). Documented in README.
4. **Add Redis cache** before running `--workers > 1`. The current
   in-process cache is not thread-safe.
5. **Keep schema changes on Alembic.** Revisions 0001 and 0002 exist;
   subsequent changes should follow the same
   `revision --autogenerate` -> review -> `upgrade head` pattern.
6. **If a document format other than PDF/DOCX/TXT/MD is needed**, add a
   parser function plus a registry entry in `parsers.py`.

---

See `HLD.md` for architectural decisions and phase status, and
`docs/MEMORY.md` for the war stories behind every non-obvious fix.
```

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
git add LLD.md
git commit -m "Docs: correct LLD §9 next steps, add current eval results to §8"
git push
```

Git bash terminal code : & "C:\Program Files\Git\git-bash.exe" --cd="C:\Users\ADMIN\Desktop\rag-platform"