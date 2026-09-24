Here is the complete `docs/ARCHITECTURE.md`. Save it at `backend/../docs/ARCHITECTURE.md` — i.e. the `docs/` folder at the repo root.

```markdown
# Architecture — Modern RAG Platform

**Companion docs:** `../HLD.md` (decisions & phase status), `PRD.md`
(requirements), `DESIGN.md` (deep design), `RULES.md` (invariants),
`MEMORY.md` (war stories), `../README.md` (user-facing).

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
        │ ─ chunks (vec + tsv  │         │   v1.5, 384-dim, CPU)   │   │   ↓ fallback          │
        │   + modality)        │         │                         │   │  Ollama (text +       │
        │ ─ conversation_turns │         │                         │   │   vision:moondream)   │
        │ ─ feedback           │         └─────────────────────────┘   └───────────────────────┘
        └──────────────────────┘
```

**Stateful services:** exactly one — Postgres. It holds metadata, vectors,
full-text index, conversation history, and feedback. There is no separate
vector DB, no Elasticsearch, no Redis (yet), no object store (the local
filesystem is the swap point for S3/GCS).

**External calls:** embeddings and reranker are **local** (no network at
query time). The LLM is the only networked component, and it has a local
fallback. Vision uses the same Ollama server as the fallback LLM.

---

## 2. Repository Layout

```
rag-platform/
├── docker-compose.yml          postgres + backend + frontend
├── .env / .env.example         single source of config
├── HLD.md / README.md
├── docs/                       PRD, ARCHITECTURE, RULES, DESIGN, TASKS, MEMORY
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
│   │   ├── main.py                    FastAPI app, lifespan, middleware, exceptions
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
│   │   │   ├── validation.py          MIME type + size validation
│   │   │   ├── storage.py             write uploads to disk
│   │   │   ├── parsers.py             Docling for PDF/DOCX; plain read for TXT/MD
│   │   │   ├── cleaning.py            whitespace normalization
│   │   │   ├── chunking.py            fixed + recursive text; whole-table markdown
│   │   │   └── pipeline.py            orchestration, per-modality routing
│   │   ├── embeddings/
│   │   │   ├── base.py, local.py, openai_provider.py, provider.py
│   │   ├── retrieval/
│   │   │   ├── vector_store.py        pgvector HNSW cosine search
│   │   │   ├── keyword_store.py       Postgres full-text ts_rank_cd
│   │   │   ├── hybrid.py              min-max fusion + modality boost
│   │   │   ├── metadata.py            JSONB containment filter
│   │   │   ├── reranker.py            bge-reranker-base cross-encoder
│   │   │   ├── query_transform.py     rewrite_query + expand_queries
│   │   │   └── compression.py         containment dedup + budget selection
│   │   ├── generation/
│   │   │   ├── llm_client.py          frozen LLMClient interface
│   │   │   ├── providers.py           OpenAI-compatible client + fallback chain
│   │   │   ├── prompt.py              SYSTEM_PROMPT (5 rules) + user prompt builder
│   │   │   └── vision.py              moondream image description
│   │   ├── orchestrator/
│   │   │   ├── naive_rag.py           baseline pipeline
│   │   │   └── improved_rag.py        hybrid + rerank + compression + rewrite
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
    ├── regenerate_report.py           re-render markdown from JSON
    ├── golden_dataset.json
    ├── sample_corpus/
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
parsers.py ────── Docling parse (PDF/DOCX) → ParsedDocument:
                    text_units    : merged by section
                    table_units   : markdown strings
                    picture_units : PNG bytes + alt text
   │
   ▼
cleaning.py ───── normalize text, preserve headings
   │
   ▼
chunking.py ───── text:   recursive or fixed (by ChunkingStrategy)
                  tables: one chunk per table, markdown, never split
   │
   ▼
pipeline._build_image_chunks()
   │  ┌─ describe_image() → moondream:1.8b via Ollama
   │  ├─ save PNG to data/uploads/<doc_id>/images/<idx>.png
   │  └─ build image chunk:
   │       "Alternate text for this image: ..." +
   │       "This image depicts: ..."
   ▼
embeddings/local.py ── bge-small-en-v1.5 → 384-dim vectors
   │
   ▼
persist ────────── chunks rows:
                    content, chunk_index, page_number, section_title,
                    token_count, modality, chunk_metadata, embedding
                    (content_tsv is a generated column)
   │
   ▼
documents.status = READY   (or FAILED + failure_reason)
```

**Key invariants:**
- Every stage is wrapped; a bad file marks the document `FAILED` with a
  reason and never raises past the background-task boundary.
- `chunks.document_id` has `ON DELETE CASCADE` — deleting a document
  deletes its chunks.
- `content_tsv` is a **persisted generated column**; the app never writes
  it directly.
- **Tables are never split by row.** Splitting destroys row/column
  associations — one table = one chunk.
- **Image alt text is authoritative over vision descriptions.** Prompt
  rule 5 enforces this at generation time.

**Parser behavior (verified against real documents):**

| Format | Behavior |
|---|---|
| **PDF** | Docling extracts text, headings, lists, tables, pictures. Page numbers come from `prov` metadata. Images are not always classified as PictureItems — some PDFs encode them as vector graphics. |
| **DOCX** | Docling extracts text, headings, lists, tables. Alt text extracted via a supplementary `wp:docPr` XML walk (python-docx's `inline_shapes` misses floating images). |
| **TXT / MD** | Plain UTF-8 read. No structure detection. |

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

Fast (~65 ms warm). Vector-only retrieval. This is the pipeline the demo
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
[retrieve] ── if ENABLE_MULTI_QUERY: expand_queries() → up to 3 paraphrases
   │            each paraphrase → hybrid_search()
   │            hybrid_search applies modality boost when query has an
   │            image keyword (chart/image/figure/diagram/photo/etc)
   │            merge: keep best score per chunk_id
   │
   ▼
[relevance gate] ── max( raw_vector_relevance of resolved_query,
   │                      raw_vector_relevance of original question,
   │                      keyword_ts_rank > 0 )
   │            threshold 0.6 — relaxed to 0.35 when query has an
   │            image keyword AND an image chunk is in the pool
   │
   ├─ empty OR below threshold → abstain
   │
   ▼
[rerank] ── cross-encoder rerank, top_n = RERANK_TOP_N
   │          REORDERS; does NOT filter — cross-encoder scores are
   │          not calibrated 0–1
   │
   ▼
[modality guarantee] ── if query has an image keyword AND rerank
   │                      dropped every image chunk, splice the best
   │                      image candidate back into final_chunks
   │
   ▼
[compression] ── containment dedup + greedy select within CONTEXT_TOKEN_BUDGET
   │
   ├─ empty → abstain
   │
   ▼
build grounded prompt (with history) → llm.generate()
   │
   ▼
answer + citations (abstained reconciled with LLM output)
```

**Asymmetry to remember:** baseline abstains at one point (after vector
filter). Improved abstains at **two** retrieval-side points plus the
post-generation check.

**Why the improved pipeline is much slower:**
- Rewrite (when history exists): 1 LLM call
- Multi-query (when enabled): 1 LLM call
- Generation: 1 LLM call
- Hybrid retrieval: two queries (vector + keyword) per paraphrase
- Reranker: cross-encoder inference on CPU over ~24 candidates
- Compression: dedup + budget selection

The baseline does exactly one embedding + one vector search + one LLM call.

---

## 5. Retrieval Subsystem

### 5.1 Hybrid Fusion (`retrieval/hybrid.py`)

```
candidate_k = top_k * candidate_multiplier   # default 3
v = vector_search(candidate_k)               # cosine similarity
k = keyword_search(candidate_k)              # ts_rank_cd

v_norm = min_max_normalize(v)                # empty → {}; all-equal → 1.0
k_norm = min_max_normalize(k)

for chunk_id in (v_norm ∪ k_norm):
    combined = alpha * v_norm.get(id, 0) + (1-alpha) * k_norm.get(id, 0)

# Modality boost — applied BEFORE sorting so a low-scoring image chunk
# can rise into the top-k
if query contains an image keyword:
    for chunk in blended:
        if chunk.content starts with an image-chunk prefix:
            chunk.score *= 2.5

blended.sort(by combined score desc)
return blended[:top_k]
```

`alpha = HYBRID_ALPHA` (default 0.5).

**Why min-max normalization:** cosine and `ts_rank_cd` live on
incomparable numeric scales. Combining raw values would let whichever
happens to have a larger typical range dominate regardless of `alpha`.

**The trap min-max creates:** the top candidate is guaranteed near 1.0
**even when the whole candidate set is irrelevant.** This is a property,
not a bug. It is why the fused score is unsuitable as an abstention
gate.

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
(`@lru_cache`), **forced to `device="cpu"` with
`low_cpu_mem_usage=False`** — see `RULES.md` for why this is not
removable.

Scores **replace** the chunk's prior score entirely; they are not blended
with hybrid score.

**Critical empirical finding:** `bge-reranker-base` scores are **not
calibrated 0–1**. For a vocabulary-mismatched query ("PTO accrual amount"
vs. corpus text "paid annual leave"), the cross-encoder correctly ranked
the right chunk #1 **but scored it 0.0056**. Applying a `>= 0.15` filter
silently vetoed a genuinely correct match. Reranking **reorders, never
gates.**

### 5.5 Vector Search (`retrieval/vector_store.py`)

pgvector HNSW index (`vector_cosine_ops`), created at app startup (its
DDL is not expressible through SQLAlchemy's `Index()`). Cosine distance.
`EMBEDDING_DIM=384` is baked into the column type; changing the model
requires re-ingestion.

### 5.6 Modality Detection

Retrieval code does not have a `modality` field on `RetrievedChunk` (the
lightweight dataclass returned by `vector_search`/`hybrid_search`).
Instead, image chunks are **structurally identifiable by their content
prefix:**

```python
_IMAGE_CHUNK_PREFIXES = ("Alternate text for this image", "This image depicts")
is_image = chunk.content.startswith(_IMAGE_CHUNK_PREFIXES)
```

This is guaranteed by construction — every image chunk is built by
`pipeline._build_image_chunks()` with those prefixes. It avoids a schema
change on `RetrievedChunk` and keeps the retrieval layer decoupled from
the chunking layer's modality model.

### 5.7 Abstention Gate

Three score types flow through the pipeline. Only one is safe to gate on.

| Score | Range | Property | Gate-safe? |
|---|---|---|---|
| Raw vector cosine | [0, 1] absolute | calibrated similarity | ✅ |
| Hybrid fused | [0, 1] per-query | min-max normalized | ❌ always tops near 1.0 |
| Cross-encoder | unbounded | not calibrated | ❌ correct match can score 0.005 |

**The rule:** abstention gates on **raw cosine of the resolved question**.

Empirical calibration on this corpus (`bge-small-en-v1.5`):
- Relevant question: **0.84**
- "What is the company's stock price?": **0.50**
- "What is the capital of France?": **0.38**

Small sentence-embedding models suffer **anisotropy** — unrelated English
text clusters with a similarity floor well above 0. 0.6 sits above both
noise samples and below real signal.

**Modality exception:** when the query contains an image keyword AND an
image chunk exists in the candidate pool, the threshold relaxes to
**0.35**. This closes the "modality gap" — text queries embed slightly
farther from image descriptions than from text.

---

## 6. Generation Subsystem

### 6.1 LLM Client Interface

`llm_client.py` defines the frozen interface:

```python
class LLMClient:
    def generate(self, system: str, user: str) -> str: ...
```

**Frozen by design.** Both orchestrators call it in multiple places
(rewriting, multi-query expansion, final answer). Extending the interface
breaks every call site silently. New behavior must be wrapped, not added.

### 6.2 Provider Chain (`providers.py`)

One `_OpenAICompatibleClient` handles any OpenAI-compatible endpoint.
Both Gemini and Ollama qualify — only `base_url`, `api_key`, and `model`
differ between instances.

`FallbackLLMClient` tries primary; on **any** exception logs
`primary_llm_failed_falling_back_to_ollama` and calls fallback.

`get_llm_client()` builds the chain:

```
Gemini key 1 → Gemini key 2 → ... → Gemini key N → Ollama
```

This is achieved by nesting `FallbackLLMClient` N times, with Ollama as
the innermost fallback. No multi-key-aware client class is needed.

**Token usage logging:** every successful call logs `llm_usage` with
`prompt_tokens`, `completion_tokens`, `total_tokens` when the provider
exposes them.

### 6.3 Prompt (`prompt.py`)

`SYSTEM_PROMPT` enforces five rules:

1. Answer **only** from the provided numbered sources.
2. **Cite** supporting sources in `[n]` format.
3. If the sources are insufficient, respond exactly with the abstention
   message — do not guess.
4. Be concise; do not repeat the question.
5. **Alt text is authoritative over vision descriptions.** When a source
   contains both `"Alternate text for this image:"` and `"This image
   depicts:"`, the alternate text wins. Use the description only to
   supplement, never to contradict.

`build_user_prompt(resolved_query, chunks, history)`:
- Includes prior conversation turns when present
- Numbers each chunk so citations map to a specific retrieved item
- Truncates chunk text to a bounded excerpt per chunk

### 6.4 Vision (`vision.py`)

`describe_image(image_bytes) -> str` — sends the PNG to
`moondream:1.8b` via Ollama's OpenAI-compatible endpoint. Returns `""` on
any failure; ingestion never fails because one image couldn't be
described. Token limit is set via `VISION_MAX_TOKENS` (default 60) to
keep descriptions terse — long descriptions dilute the embedding.

**Design rationale:** vision is a separate module from
`providers.py`. The `LLMClient` interface is text-only by contract;
vision passes image bytes alongside the prompt and needs its own small
interface.

---

## 7. Frontend (Streamlit)

`frontend/app.py` is a **pure HTTP client** — it never imports `app.*`
and never touches Postgres.

Four tabs:

| Tab | Action | Backend call |
|---|---|---|
| **Chat** | ask a question | `POST /query` with `session_id` |
| **Upload** | upload a file, poll for ready | `POST /documents`, `GET /documents/{id}` |
| **Documents** | list everything ingested | `GET /documents` |
| **Settings** | pipeline toggle, API token | — |

Session state (`st.session_state.session_id`) persists a UUID across
Streamlit reruns so follow-up questions work. `New conversation` resets
it. Feedback buttons write to `POST /feedback`.

---

## 8. Persistence Layer

Single Postgres instance. Four tables:

| Table | Role | Notes |
|---|---|---|
| `documents` | Uploaded file metadata + ingestion status | `doc_metadata` JSONB for free-form filtering |
| `chunks` | Text + embedding + generated tsvector + modality + chunk metadata | HNSW on `embedding`; GIN on `content_tsv`; index on `modality` |
| `conversation_turns` | Short-term conversation history | Keyed by client-generated `session_id` |
| `feedback` | Useful/not-useful + optional comment | Written by `POST /feedback` |

**Schema management:** Alembic. Revision `0001` is the baseline. Revision
`0002` added `chunks.modality` (`varchar(16)`, default `'text'`) and
`chunks.parent_chunk_id` (nullable self-referencing FK) plus a
`ix_chunks_modality` index.

**Enum casing gotcha:** `DocumentStatus` values are stored **uppercase**
in Postgres (`READY`, `FAILED`) even though Python defines them
lowercase. Any raw SQL must use uppercase labels.

---

## 9. Deployment

`docker-compose.yml`:

- **`postgres`** — `pgvector/pgvector:pg16`, healthchecked via
  `pg_isready`. Host port **5433** (moved off 5432 to avoid a collision
  with a native Windows Postgres install — see `MEMORY.md`).
- **`backend`** — FastAPI + uvicorn, depends on `postgres` healthy.
  Env overrides `DATABASE_URL` to use the `postgres` service name
  instead of `localhost`, so both host-side tools and container
  processes work off the same `.env`.
- **`frontend`** — Streamlit, talks to `http://backend:8000` by service
  name.

Volumes:

| Volume | Purpose |
|---|---|
| `pgdata` | Database |
| `upload_data` | Uploaded files + extracted image artifacts |
| `hf_cache` | HuggingFace model cache (embedding, reranker, Docling layout models) |

**Critical:** the `hf_cache` volume is load-bearing. Without it, the
embedding and reranker models re-download on every container recreate,
which re-triggers the "meta tensor" failure mode on flaky networks.

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
| Vision | `generation/vision.py` | `OLLAMA_VISION_MODEL` |
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
- **Local embeddings, reranker, and vision.** Zero required API keys for
  the retrieval and image-description halves. Only text generation
  touches the network — and it has a local fallback.
- **Streamlit, not React.** The spec asks for "a simple web UI".
  Streamlit delivers it in one file, and the backend API is the same
  either way.
- **Whole-table chunks, not row-split.** Splitting tables destroys
  row/column associations. The cost is that a very large reference table
  becomes one large chunk; the recursive chunker's budget check still
  allows it through if nothing else fits.
- **Image chunks carry alt text first, description second.** Alt text is
  document-authoritative; description is machine-generated and
  supplementary. Prompt rule 5 makes this explicit to the LLM.

---

## 12. What the Architecture Does Not Do

Documented intentionally, so a future contributor doesn't discover these
the hard way:

- **No OCR.** Scanned PDFs (image-only pages) are not extractable.
- **No multimodal embedding.** Text, tables, and images all become text
  at ingestion — there is no shared vector space between an image and a
  text query about the image's pixels. The vision description bridges
  that gap semantically, not visually.
- **No cross-document joins.** Each chunk is retrieved independently.
  Multi-document synthesis is a generation-time capability (the LLM
  combines retrieved chunks) — there is no query planner that fans out
  and joins.
- **No streaming.** Generation is synchronous; the frontend waits for
  the full answer.
- **No agentic control flow.** The pipeline is a fixed DAG. The LLM
  makes decisions *within* a step (which paraphrase to generate, what to
  answer), not about the flow.
- **No per-user isolation.** One shared bearer token; all documents are
  visible to all users.
```

---

That's the complete `docs/ARCHITECTURE.md`. Save it, then move on to the other three files (`README.md`, `HLD.md`, `docs/MEMORY.md`) if you want them fresh too — or just replace this one if the others are already close enough.