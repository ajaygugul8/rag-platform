Here's the complete `README.md`, written as an agent handoff. It leads with what works and how to run it, then the architecture, then the known limitations, then exactly what to do next. Replace your current `README.md` with this.

```markdown
# Modern RAG Platform

**Status:** Working end to end. 23 tests passing. Evaluated on a
20-question benchmark.

**For an agent or engineer picking this up:** read sections 1-4 first
(15 min) to orient. Sections 5-7 are reference. Section 8 is exactly
what to do next.

---

## 1. What this is

An internal knowledge assistant: users upload documents (PDF, DOCX, TXT,
Markdown), ask questions in natural language, and get answers grounded
in those documents with source citations. The system abstains when the
corpus doesn't contain the answer.

It is a **demonstration of the modern RAG stack**, not a toy:
- Multimodal ingestion — text, tables, and images become first-class
  chunks that flow through the same retrieval pipeline
- Two retrieval pipelines (baseline vector-only vs. improved
  hybrid+rerank) that can be A/B compared on the same evaluation set
- Repeatable evaluation with quantitative metrics
- Structured tracing on every pipeline stage

**The headline number:** on a 20-question benchmark, the improved
pipeline achieves a 0.94 retrieval hit rate vs. 0.83 for the baseline.

---

## 2. Current state — what works, what doesn't

### Works (verified end to end)
- Upload → parse → chunk → embed → persist for PDF, DOCX, TXT, MD
- Text chunks, table chunks (markdown), image chunks (described + alt text)
- Hybrid retrieval (vector + keyword, min-max fused)
- Cross-encoder reranking (reorders; never gates)
- Conversation-aware query rewriting (with safety net for standalone questions)
- Multi-query expansion (config-gated)
- Contextual compression (containment dedup + budget selection)
- Grounded generation with citations
- Three-stage abstention (retrieval → compression → LLM output)
- Gemini multi-key rotation with Ollama fallback
- Streamlit chat frontend with citations, feedback, session history
- Alembic migrations (0001 initial, 0002 multimodal)
- 23 automated tests
- Evaluation harness with a 20-question golden set

### Known limitations (documented, not bugs to fix blindly)
- **Vision descriptions are non-authoritative.** moondream:1.8b
  correctly identifies images but can mislabel subjects. Prompt rule 5
  makes document-supplied alt text authoritative over machine-generated
  descriptions.
- **PDF images are not always classified as PictureItems.** Depends how
  the PDF encodes them. The 50-page sample PDF yields 0 PictureItems
  despite containing charts.
- **Scanned PDFs are not supported.** No OCR layer. A page that is one
  big image produces no extractable text.
- **Windows host pytest fails** with `DLL load failed while importing
  _argkmin`. This is Windows Application Control blocking a scikit-learn
  binary. Run tests in Docker instead.
- **Multi-query preserves jargon** rather than bridging to corpus
  vocabulary. LLM bridges the gap at generation time.
- **Cache is not thread-safe.** In-process LRU+TTL. Fine for one worker.
- **No per-user auth.** One shared bearer token; every document visible
  to anyone with the token.
- **No concurrent-user testing.**
- **No load testing.**

---

## 3. Quick start

### Prerequisites
- Docker Desktop
- Python 3.11+ (for host-side scripts like the eval harness)
- Ollama (optional — required only for image descriptions and LLM fallback)

### Run it

```bash
git clone https://github.com/ajaygugul8/rag-platform.git
cd rag-platform
cp .env.example .env
# Edit .env — set GEMINI_API_KEYS and POSTGRES_PASSWORD
docker compose up --build
```

First startup downloads ~2 GB of models into a persistent `hf_cache`
Docker volume. Requires internet the first time only.

Then:
- Frontend: http://localhost:8501
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Pull the vision model (optional, for image descriptions)

```bash
ollama pull moondream:1.8b
```

Without this, images still ingest but with empty descriptions.

### Run the tests

```bash
docker compose exec backend pytest -v
# Expected: 23 passed
```

**Do not run pytest on the Windows host.** It fails on a DLL block.
Always run it inside the container.

### Run the evaluation

```bash
python eval/run_eval.py
```

Ingests 4 sample docs, runs 20 golden questions through both pipelines,
writes JSON + Markdown report to `eval/results/`. First run downloads
models and takes ~5 min; later runs are faster.

---

## 4. Architecture at a glance

```
Upload → Validation → Storage → [background] Ingestion Pipeline
                                    │
                                    ▼
                          Docling parse (PDF/DOCX) or plain read
                                    │
                        ┌───────────┼───────────┐
                        ▼           ▼           ▼
                    text_units  table_units  picture_units
                        │           │           │
                        ▼           ▼           ▼
                    chunker    markdown     vision desc
                    (recursive) (whole)     + DOCX alt text
                        │           │           │
                        └───────────┴───────────┘
                                    ▼
                          embed (bge-small-en-v1.5, 384-dim)
                                    ▼
                          persist with modality tag
                                    ▼
                              chunks table

Query → Orchestrator (baseline | improved)
            │
    ┌───────┴────────┐
    ▼                ▼
Vector-only      Hybrid (vector + keyword)
retrieval            + modality boost
    │                │
    │            Rerank (reorders only)
    │                │
    │            Modality guarantee
    │                │
    │            [Compression]
    │                │
    └────────┬───────┘
             ▼
    Grounded prompt → LLM → answer + citations
```

**Stack:**
- Backend: FastAPI, Python 3.12
- Database: Postgres + pgvector (metadata, vectors, full-text all in one)
- Embeddings: local `BAAI/bge-small-en-v1.5` (384-dim)
- Reranker: local `BAAI/bge-reranker-base` cross-encoder
- Vision: local `moondream:1.8b` via Ollama
- LLM: Gemini (multi-key) with Ollama fallback
- Frontend: Streamlit (pure HTTP client)
- Migrations: Alembic (0001, 0002)
- Deployment: Docker Compose

---

## 5. Repository layout

```
rag-platform/
├── docker-compose.yml              postgres + backend + frontend
├── .env / .env.example             single source of config
├── HLD.md                          architecture + decisions + phase status
├── LLD.md                          module detail, schemas, API contracts
├── README.md                       this file
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md             deeper module layout
│   ├── RULES.md                    invariants and landmines
│   ├── DESIGN.md                   deep design rationale
│   ├── TASKS.md                    current task tracker
│   └── MEMORY.md                   war stories, gotchas
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_add_chunk_modality.py
│   ├── app/
│   │   ├── main.py                 FastAPI app, lifespan, middleware
│   │   ├── config.py               the ONLY module that reads os.environ
│   │   ├── api/
│   │   │   ├── documents.py        POST/GET /documents
│   │   │   ├── query.py            POST /query
│   │   │   ├── feedback.py         POST /feedback
│   │   │   └── schemas.py          Pydantic models
│   │   ├── core/
│   │   │   ├── security.py         Bearer auth (HTTPBearer)
│   │   │   ├── exceptions.py       Domain exception hierarchy
│   │   │   └── cache.py            In-process LRU+TTL
│   │   ├── db/
│   │   │   ├── models.py           documents, chunks, conversation_turns, feedback
│   │   │   ├── session.py
│   │   │   └── base.py
│   │   ├── ingestion/
│   │   │   ├── validation.py
│   │   │   ├── storage.py
│   │   │   ├── parsers.py          Docling for PDF/DOCX; plain read for TXT/MD
│   │   │   ├── cleaning.py
│   │   │   ├── chunking.py         fixed + recursive; table markdown
│   │   │   └── pipeline.py         orchestrates ingestion, per-modality routing
│   │   ├── embeddings/
│   │   │   ├── local.py            bge-small-en-v1.5
│   │   │   └── provider.py         factory
│   │   ├── retrieval/
│   │   │   ├── vector_store.py     pgvector HNSW cosine
│   │   │   ├── keyword_store.py    Postgres ts_rank_cd
│   │   │   ├── hybrid.py           min-max fusion + modality boost
│   │   │   ├── metadata.py         JSONB containment filter
│   │   │   ├── reranker.py         bge-reranker-base
│   │   │   ├── query_transform.py  rewrite_query + expand_queries
│   │   │   └── compression.py      containment dedup + budget
│   │   ├── generation/
│   │   │   ├── llm_client.py       frozen LLMClient interface
│   │   │   ├── providers.py        Gemini multi-key + Ollama fallback
│   │   │   ├── prompt.py           SYSTEM_PROMPT (5 rules)
│   │   │   └── vision.py           moondream image description
│   │   ├── orchestrator/
│   │   │   ├── naive_rag.py        baseline pipeline
│   │   │   └── improved_rag.py     hybrid + rerank + compression + rewrite
│   │   ├── conversation/history.py
│   │   └── observability/
│   │       ├── logging.py          JSON formatter
│   │       └── tracing.py          trace_stage context manager
│   └── tests/
│       ├── test_documents.py
│       ├── test_chunking.py
│       ├── test_hybrid.py
│       ├── test_phase3_hybrid_retrieval.py
│       ├── test_phase3b_tables.py
│       ├── test_phase4_advanced.py
│       └── test_query_e2e.py
├── frontend/
│   ├── Dockerfile
│   └── app.py                      Streamlit UI (pure HTTP client)
└── eval/
    ├── run_eval.py
    ├── regenerate_report.py
    ├── golden_dataset.json         20 questions
    ├── sample_corpus/              5 documents
    └── results/
```

---

## 6. API contract

All routes require `Authorization: Bearer <API_AUTH_TOKEN>`.

### `POST /documents`
`multipart/form-data`:
- `file` — pdf/docx/txt/md, ≤ `MAX_UPLOAD_MB` (25 default)
- `metadata` — optional JSON object string

Returns `201` with `{"id", "filename", "status": "uploaded", ...}`.
Ingestion runs async. Poll `GET /documents/{id}` until `status` is
`ready` or `failed`.

### `POST /query`
```json
{
  "question": "string, required",
  "pipeline": "baseline" | "improved",
  "document_ids": ["uuid"] | null,
  "filters": {"department": "hr"} | null,
  "session_id": "string" | null
}
```

Returns:
```json
{
  "answer": "string",
  "abstained": false,
  "pipeline": "improved",
  "resolved_query": "string | null",
  "citations": [
    {"document_id": "uuid", "filename": "policy.pdf", "page_number": 3,
     "section_title": null, "score": 0.81, "excerpt": "first 280 chars"}
  ]
}
```

### `POST /feedback`
`{"query": "...", "answer": "...", "is_useful": true, "comment": null}`.

### `GET /health`
`{"status": "ok", "app_env": "...", "database": "ok" | "unreachable"}`.

---

## 7. Critical design decisions (do not undo)

These are load-bearing. Each exists because a plausible-looking
simplification was wrong.

1. **Rerank reorders; it never gates.** `bge-reranker-base` scores are
   not calibrated 0-1. A correctly-ranked vocabulary-mismatched match
   scores 0.0056. Applying `score >= 0.15` silently vetoed genuine
   matches. Abstention gates upstream on raw cosine instead.

2. **Abstention gates on raw cosine, not hybrid's fused score.**
   `hybrid.py` min-max normalizes per query, so the top candidate is
   near 1.0 even when the whole set is irrelevant. Fused score = bad
   for gating. Raw cosine = good.

3. **Tables are never split.** One table = one chunk, markdown
   serialized. Splitting by row destroys row/column associations.

4. **Image alt text is authoritative over vision descriptions.** Prompt
   rule 5 enforces this. Without it, moondream's imprecise descriptions
   leak verbatim into answers.

5. **Modality boost + guarantee + gate relaxation.** Three additive
   retrieval fixes that close the "text query → image answer" gap. All
   three are additive — text-only queries skip them.

6. **`device="cpu"` + `low_cpu_mem_usage=False` in model loading.**
   Without this, newer `transformers`/`accelerate` load weights via a
   "meta device" that fails on interrupted downloads with an error that
   doesn't mention download. Do not "clean up" these kwargs.

7. **`LLMClient` interface is frozen.** `generate(system, user) -> str`.
   Both orchestrators call it in multiple places. Extending it breaks
   every call site silently.

8. **Config is centralized in `config.py`.** No other module reads
   `os.environ`. This makes "secrets never hard-coded" auditable.

9. **Alembic, not `create_all()`.** `create_all()` only adds tables; it
   silently does nothing when a column is added to an existing table.
   That caused a real crash.

10. **`DocumentStatus` values are stored uppercase in Postgres.**
    Lowercase in Python, uppercase in the DB. Raw SQL must use `'READY'`,
    not `'ready'`.

---

## 8. What to do next

In priority order.

### 8.1 Fix the Word table extraction edge case
**Status:** identified, not yet fixed.
**Owner's note:** cause is known. Look at `ingestion/parsers.py`,
specifically how Docling `TableItem`s are detected in DOCX files vs.
PDFs. Some Word tables are being skipped entirely.

### 8.2 Decide on image display
**Status:** open decision.
**Context:** image chunks exist, descriptions and alt text are in the
chunk content, but the actual PNG is not shown in the frontend. To add
inline display you would:
1. Add a route to serve the PNG (with auth)
2. Include a base64-encoded image or URL in the query response for image citations
3. Render an `<img>` tag in `render_sources()` in `frontend/app.py`

Decide whether to display inline, link to source, or leave as-is.

### 8.3 Test concurrent users
**Status:** not done.
**Approach:** run 10 parallel queries via `locust` or a simple Python
`ThreadPoolExecutor` script. Watch for:
- The cache corrupting under concurrent access (`core/cache.py` is not
  thread-safe)
- Ingestion getting blocked while a query runs (BackgroundTasks is
  in-process, single-worker)

### 8.4 Write a walkthrough doc
**Status:** README/HLD/LLD/docs exist but no single short "start here."
**Deliverable:** `docs/WALKTHROUGH.md` — first-hour orientation for a
new engineer. Sections: what you're looking at, get it running, try it,
run tests, understand architecture, run eval, first safe change,
common pitfalls.

### 8.5 Optional — production hardening
Not required for the demo. Documented in `HLD.md` §9.
- Redis cache (replace in-process cache before `--workers > 1`)
- Task queue (replace `BackgroundTasks` for parallel ingestion)
- Per-user auth (replace shared token)

---

## 9. Common pitfalls and how to avoid them

### Run pytest in Docker, not on Windows
```bash
docker compose exec backend pytest -v    # correct
pytest -v                                 # fails on Windows
```
Windows Application Control blocks `_argkmin.pyd` (a scikit-learn
binary pulled in by Docling). The container is Linux and unaffected.

### `.env` must be at the repo root
Not in `backend/`. `config.py` resolves it relative to the file, but
commands that read from CWD need to run from the repo root.

### Postgres is on 5433, not 5432
There's a native Windows Postgres that owns 5432. Docker's Postgres is
mapped to 5433. If you connect to `localhost:5432` with psql, you'll hit
the wrong database.

### `HF_HUB_OFFLINE=1` blocks Docling's first download
If Docling errors with `OfflineModeIsEnabled` on first parse,
temporarily set `HF_HUB_OFFLINE=0` in `docker-compose.yml`, run one
parse, then flip it back. Models cache in the `hf_cache` volume.

### Query takes 30-60 seconds
Normal for the improved pipeline with multi-query enabled. Set
`ENABLE_MULTI_QUERY=false` in `.env` for a ~20s speedup.

### Gemini falls back to Ollama constantly
Free tier is 20 requests/day per Google Cloud project. Multiple keys
inside one project share the quota. To get more, create each key in a
separate project.

---

## 10. Reproducing the evaluation result

```bash
# Run the eval
python eval/run_eval.py

# Find the latest report
ls -t eval/results/*.md | head -1

# Read it
cat $(ls -t eval/results/*.md | head -1)
```

**Expected in the summary:**
```
baseline: hit_rate=0.83 mrr=0.81 keyword_coverage=0.81 abstention_accuracy=0.85
improved: hit_rate=0.94 mrr=0.94 keyword_coverage=0.89 abstention_accuracy=0.95
```

`hit_rate` is the "retrieval accuracy" metric — fraction of the 20
questions where the expected source document appeared in the returned
citations.

The eval harness ingests its own sample corpus (`eval/sample_corpus/`,
5 files) scoped by `document_ids`, so it's unaffected by anything you
upload as a user.

---

## 11. Reference docs

| Document | What it contains |
|---|---|
| `HLD.md` | Architecture, tech decisions, phase status, war stories |
| `LLD.md` | Module detail, data model, API contract, algorithms |
| `docs/ARCHITECTURE.md` | Deeper module layout with diagrams |
| `docs/MEMORY.md` | Every non-obvious fix and why it exists |
| `docs/RULES.md` | Invariants, landmines, prohibited changes |
| `docs/DESIGN.md` | Deep design rationale for each subsystem |

Terminal testing :
$body = @{ question = "what is the cricket rules pdf contains?"; pipeline = "improved" } | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
  -Headers @{ Authorization = "Bearer change-me-dev-token" } `
  -ContentType "application/json" `
  -Body $body

$body = @{ question = "What tables does this document contains(Sample Table-Rich Document)?"; pipeline = "baseline" } | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
    -Headers @{ Authorization = "Bearer change-me-dev-token" } `
    -ContentType "application/json" -Body $body | Format-List



docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT c.modality, COUNT(*) AS chunks, AVG(c.token_count)::int AS avg_tokens
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE d.filename ILIKE '%action%' OR d.filename ILIKE '%presentation%'
GROUP BY c.modality ORDER BY c.modality;
"