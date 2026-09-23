## `docs/DESIGN.md`

Save at `docs/DESIGN.md`.

```markdown
# Detailed Design — Modern RAG Platform

**Companion docs:** `ARCHITECTURE.md` (system-level),
`RULES.md` (invariants & landmines),
`../LLD.md` (schemas & API contracts),
`../HLD.md` (decisions & phase status).

This document explains *why* the system is built the way it is — the
reasoning behind the algorithms, the trade-offs, and the failure modes
each choice exists to prevent. For "how to use" and "what to not touch",
see `RULES.md`. For module-level structure, see `ARCHITECTURE.md`.

---

## 1. Data Model

### 1.1 `documents`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `filename` | varchar(512) | |
| `content_type` | varchar(128) | one of 4 allowed MIME types |
| `size_bytes` | int | |
| `storage_path` | varchar(1024) | local path; swap point for S3/GCS |
| `status` | enum | `UPLOADED / PROCESSING / READY / FAILED` |
| `failure_reason` | text, nullable | set only when `status = FAILED` |
| `doc_metadata` | JSONB | free-form filterable metadata |
| `created_at`, `updated_at` | timestamptz | |

**Why JSONB for `doc_metadata`:** metadata filtering (spec §5) should not
require a schema migration every time a new filterable field appears.
JSONB containment checks let `{"department":"hr"}` compose freely with
`{"category":"policy"}` without touching the schema.

**Why `FAILED` is a first-class status, not an exception:** a bad PDF or
DOCX should not crash the ingestion background task. Every stage in the
pipeline is wrapped; failure marks this document with a reason and lets
every other document continue.

### 1.2 `chunks`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK, `ON DELETE CASCADE` | |
| `content` | text | |
| `chunk_index` | int | order within document |
| `page_number` | int, nullable | from PDF parsing |
| `section_title` | varchar(512), nullable | from DOCX heading parsing |
| `token_count` | int | `words × 1.3` (approximate) |
| `chunk_metadata` | JSONB | e.g. `{"chunking_strategy": "recursive"}` |
| `embedding` | `vector(384)` | nullable until ingestion completes |
| `content_tsv` | `tsvector` **generated**, persisted | Postgres-maintained |
| `created_at` | timestamptz | |

Indexes:
- btree on `document_id` (`ix_chunks_document_id`)
- **GIN** on `content_tsv` (`ix_chunks_content_tsv`)
- **HNSW** (`vector_cosine_ops`) on `embedding` — created at app startup,
  not via SQLAlchemy `Index()`, because pgvector's index DDL is not
  expressible that way.

**Why HNSW, not ivfflat:** ivfflat needs pre-existing data to build a
useful index (it clusters existing vectors). HNSW builds incrementally
and works from an empty table — which matters for a demo that starts
empty and gets progressively populated.

**Why `content_tsv` is a generated column:** it must always reflect
`content`, and the app should never write to it. Postgres computes it on
insert and update. If you change `content`, `tsv` follows automatically,
with no code change.

**Why `token_count` is approximate:** `word_count × 1.3` is a rough but
cheap proxy. It is accurate enough for the compression budget
(`CONTEXT_TOKEN_BUDGET`) but **not** for billing or hard context-window
limits. If either becomes a requirement, swap `approx_token_count` for
`tiktoken` or the model's own tokenizer.

### 1.3 `conversation_turns`

`id, session_id (client-generated), role ("user"|"assistant"), content, created_at`.
Indexed on `(session_id, created_at)`. Only `conversation/history.py`
reads it.

**Why client-generated `session_id`:** no server-side session management
needed, and Streamlit's `st.session_state.session_id` (a UUID that
persists across reruns) is the natural client. The backend treats it as
an opaque string. No auth check on it — the bearer token is the only
auth boundary.

### 1.4 `feedback`

`id, query, answer, is_useful (bool), comment (nullable), created_at`.

**Why separate from `/query`:** a feedback submission is a distinct user
action that may happen seconds or minutes later, and may be revised.
Decoupling means the query endpoint stays stateless and cache-friendly
(`core/cache.py` keys on `(pipeline, question, document_ids, filters)`)
without feedback writes polluting the cache key.

---

## 2. Ingestion Pipeline

### 2.1 Why background task, not synchronous

A 2 MB / 50-page PDF takes 5–20 seconds to parse, clean, chunk, and embed.
Making the upload response wait for that blocks a worker for the duration.
FastAPI's `BackgroundTasks` runs the ingestion after the response is
sent. The client polls `GET /documents/{id}` until `READY`.

**Limitation:** `BackgroundTasks` runs in-process, single-worker. If the
API process restarts mid-ingestion, that document stays stuck in
`PROCESSING`. Production fix: Celery/RQ/arq. For a demo, restart-tolerant
statuses + polling are sufficient.

### 2.2 Parsers

| Format | Parser | Extracts | Notes |
|---|---|---|---|
| **PDF** | pdfplumber | text, page numbers | no section titles (PDFs have no heading structure the way DOCX does) |
| **DOCX** | python-docx | text, heading-based `section_title` | chapter headings become `section_title` |
| **TXT** | plain read | text | no structure |
| **MD** | plain read | text | treats markdown headings as text, not section titles |

**Verified against real documents:**
- 10-page PDF with mixed images + lorem ipsum + a metric table: all
  extracted, table flattened to text but usable.
- 50-page PDF: page numbers correct across all pages, tables extracted
  as flattened text (rows collapse onto one line).
- DOCX: `section_title` populated (e.g. "Leave Policy", "Sick Leave"),
  which is what makes DOCX citations more useful than PDF citations.

**Table extraction caveat:** PDF tables come out as flattened text — e.g.
`Market Size $50 Billion / User Satisfaction 85% / Growth Rate 10%`. Numbers
are retrievable but row/column structure is lost. RAG doesn't need
structure to answer factual queries; it does need it if you ever want
"give me the whole table as CSV".

### 2.3 Chunking strategies

**Fixed:** sliding window over `text.split()` by word count, `step =
chunk_size - overlap`.

**Recursive (structure-aware):** split on `\n\n` paragraph boundaries;
accumulate paragraphs into a buffer until adding the next would exceed
`chunk_size` tokens; flush. A single oversized paragraph falls back to
fixed-size splitting for just that paragraph.

**Why recursive is the default:** paragraphs are semantically coherent
units. Splitting mid-paragraph loses context. Splitting at paragraph
boundaries keeps each chunk self-contained while honoring a size cap.

### 2.4 Cleaning

Whitespace normalization, trailing-space stripping, smart-quote
normalization. **Headings and structure are preserved** — cleaning does
not flatten them. This is what makes DOCX `section_title` extraction
possible downstream.

---

## 3. Retrieval Algorithms

### 3.1 Hybrid fusion

```
candidate_k = top_k * candidate_multiplier     # default multiplier 3
v = vector_search(candidate_k)                 # cosine similarity
k = keyword_search(candidate_k)                # ts_rank_cd

v_norm = min_max_normalize(v)                  # empty → {}; all-equal → 1.0
k_norm = min_max_normalize(k)

for id in (v_norm ∪ k_norm):
    combined = alpha * v_norm.get(id, 0) + (1-alpha) * k_norm.get(id, 0)

return top_k by combined, descending
```

`alpha = HYBRID_ALPHA` (default 0.5). `min_max_normalize` maps an empty
dict to `{}`, and an all-equal-scores dict to all `1.0` (avoids
div-by-zero, treats ties as maximally relevant rather than arbitrarily
zero).

**Why min-max normalization:** cosine similarity and `ts_rank_cd` live
on incomparable numeric scales. Combining raw values would let whichever
score happens to have a larger typical range dominate regardless of
`alpha`.

**The trap min-max creates:** the top candidate is guaranteed near 1.0
**even when the whole candidate set is irrelevant.** This is a property,
not a bug — normalization is relative to the batch. It is also why the
fused score is unsuitable as an abstention gate (see §5).

### 3.2 Metadata filter

`build_metadata_filter({"department": "hr"})` compiles to:

```sql
Document.doc_metadata @> '{"department":"hr"}'::jsonb
```

i.e. JSONB containment. Multiple filter keys are ANDed automatically
(all keys must match). Free-form — no schema migration needed when a new
filterable field appears.

### 3.3 Reranking

`CrossEncoder("BAAI/bge-reranker-base").predict([(query, chunk), ...])`,
lazily loaded once per process (`@lru_cache`), forced to `device="cpu"`
with `low_cpu_mem_usage=False`.

Scores **replace** the chunk's existing `.score` entirely (not blended
with the hybrid score). By the time reranking runs, the hybrid score has
already done its job — picking the candidate pool. The cross-encoder
score is what orders the final answer's citations.

**Critical empirical finding:** `bge-reranker-base` scores are **not
calibrated 0–1**. For a vocabulary-mismatched query ("PTO accrual amount"
vs. corpus text "paid annual leave"), the cross-encoder correctly ranked
the right chunk #1 **but scored it 0.0056**. Applying a `>= 0.15` filter
silently vetoed a genuinely correct match.

**Resolution:** reranking **reorders, never gates.** Abstention is gated
upstream on raw cosine.

### 3.4 Vector search

pgvector HNSW, `vector_cosine_ops`, `EF_SEARCH` at default. Query-time
cost is negligible at this scale (< 50k chunks). At larger scale, tune
`ef_search` or move to a dedicated vector DB — the API doesn't change.

---

## 4. Contextual Compression

Two passes, both cheap (no LLM calls — this runs after reranking, right
before prompt construction, and shouldn't become the slowest part of the
pipeline):

### 4.1 Deduplication — current state and bug

**Current implementation:** Jaccard on 5-word shingles at threshold 0.8.

**The bug:** true Jaccard between a chunk and its suffix is capped at
`|shorter| / |longer|`. For the test case:

- `base` = 13 words → 9 shingles
- `near_dup` = `base` + 7 more words = 20 words → 16 shingles
- Intersection = 9
- Jaccard = `9 / (9 + 16 − 9)` = **0.5625**

0.5625 < 0.8, so dedup does not fire. **The function is effectively a
no-op for its intended case** — overlapping-window chunking produces
adjacent chunks that are near-duplicates by containment, not by Jaccard.

**Correct implementation:** containment (`|A∩B| / min(|A|,|B|)`) with a
length-ratio guard (`max/min > 2.0 → not a duplicate`). Containment
handles "one chunk is essentially a subset of another" — exactly the
pattern that Jaccard penalizes for the wrong reason. The ratio guard
prevents a tiny heading-only chunk from being flagged as a duplicate of
a large chunk that happens to contain its words.

**Why this matters now:** because dedup is a no-op, compression is not
reducing context for the case it was written for. Fixing it would reduce
token usage and potentially improve relevance by removing redundant
context from the prompt.

### 4.2 Budget selection

Greedily keep highest-scored, deduplicated chunks until `token_budget`
(`CONTEXT_TOKEN_BUDGET`, default 2000). Oversized single chunks are kept
only if nothing else has been selected — better one large chunk than
abstain.

**Why greedy, not knapsack:** greedy is O(n) and the chunks are already
sorted by score. A knapsack solution would pack more tokens for the same
budget but at the cost of both complexity and unpredictability — the
prompt would change based on the shape of the whole batch, making eval
numbers noisier.

---

## 5. Abstention — the Core Design Constraint

Three score types flow through the pipeline. Only one is safe to gate on.

| Score | Range | Property | Gate-safe? |
|---|---|---|---|
| Raw vector cosine | [0, 1] absolute | calibrated similarity | ✅ |
| Hybrid fused | [0, 1] per-query | min-max normalized | ❌ always tops out near 1.0 |
| Cross-encoder | unbounded | not calibrated | ❌ correct match can score 0.005 |

**The rule:** abstention gates on **raw cosine of the resolved question**.

### 5.1 Why raw cosine

Raw cosine is the only score that is *absolute* — it means the same thing
for every query, independent of what else was retrieved. Empirical
calibration on this corpus (bge-small-en-v1.5):

- Relevant question: **0.84**
- "What is the company's stock price?": **0.50**
- "What is the capital of France?": **0.38**

Small sentence-embedding models suffer from **anisotropy** — generic
English text clusters together in embedding space, producing a similarity
floor well above 0 for unrelated content. 0.6 sits above both noise
samples and below real signal.

**Calibration caveat:** 3 data points is not rigorous. Revisit once the
Phase 5 eval set has enough true-positive/true-negative pairs.

### 5.2 Why not the fused score

Min-max normalization is relative to the candidate batch. Given the
France query above, the top candidate would still normalize to ~1.0 —
because it's the best of an irrelevant set. Gating on it would answer
off-corpus questions.

### 5.3 Why not the reranker score

Not calibrated. Empirically, a correct match scored 0.0056. Any absolute
threshold on that scale is meaningless.

### 5.4 Two-stage gating in the improved pipeline

The improved pipeline performs two abstention checks:

1. **After retrieval** — raw cosine of resolved query (and original
   question, if rewritten) below 0.6, or no candidates at all
2. **After compression** — empty chunk set

Plus a third, post-generation check:

3. **After LLM generation** — the LLM echoed `ABSTENTION_MESSAGE` (the
   prompt instructs it to refuse when the context lacks the answer).
   The `abstained` flag is reconciled with this.

All three are legitimate refusals. `abstained=True` means any of them.

### 5.5 The rewrite safety net

If `rewrite_query` produced a different query, the improved pipeline
computes raw cosine for **both** the resolved query and the original
question, and takes the max. This closes the "rewrite injected context
and pointed retrieval at the wrong document" failure mode — even if the
LLM corrupts the query, retrieval still sees the user's actual words.

---

## 6. Query Transformation

### 6.1 `rewrite_query`

Triggered only when conversation history exists. The LLM converts a
follow-up ("what about sick leave?") into a standalone query ("What is
the sick leave policy?"). **Fails open** — any LLM error returns the
original question unchanged.

**Design rule (from a real bug):** the prompt must permit "return
unchanged". An earlier version said only "resolve it into a fully
standalone question using that context" — with no instruction to leave
standalone questions alone. That caused a real bug: after a turn about
the SmartHome Hub document, a new standalone question ("What was the PDF
market share in 2020 according to the table?") got rewritten to "...in
the SmartHome Hub document?" — injecting a topic never mentioned by the
user, pointing retrieval at the wrong document, and causing a false
abstention.

The prompt now includes:
- Explicit "return UNCHANGED if already standalone" rule
- Counter-examples showing standalone questions that must not be rewritten
- "Do not append context just because it appeared earlier"

The LLM's default bias is to include history whenever it's present.
The prompt has to fight that.

### 6.2 `expand_queries`

When `ENABLE_MULTI_QUERY=true`, generates up to 3 paraphrases of the
resolved question. Each is embedded and run through `hybrid_search`
independently; results merge by keeping the best score per `chunk_id`.

**Empirical limitation:** paraphrases preserve domain jargon. For "PTO
accrual amount", all variants contained "PTO" — none reached "paid annual
leave", the corpus's terminology. Multi-query improves *syntactic* recall;
it does not bridge *domain vocabulary*. The LLM bridges the residual gap
at generation time.

**Why this is documented rather than fixed:** fixing it would require
domain-specific synonym expansion (a corpus-specific thesaurus or a
fine-tuned model). Not worth the complexity for a demo. The eval
harness quantifies the current gap.

---

## 7. Prompt Design

`SYSTEM_PROMPT` enforces three rules:

1. Answer **only** from the provided context.
2. **Cite** supporting sources in `[n]` format.
3. If the context is insufficient, respond with the exact abstention
   message — do not guess.

`build_user_prompt(resolved_query, chunks, history)`:
- Includes prior conversation turns when present (for pronoun resolution)
- Numbers each chunk so citations map to a specific retrieved item
- Truncates chunk text to a bounded excerpt per chunk

The prompt is the **only** guard against hallucination after the
abstention gate passes. It is deliberately restrictive: better to abstain
than to answer from parametric knowledge.

**Post-generation reconciliation:** if the LLM outputs the abstention
message, the pipeline sets `abstained=True` — even if retrieval had
found candidates. This is the third abstention path (§5.4).

---

## 8. LLM Provider Layer

The `LLMClient` interface is exactly:

```python
class LLMClient:
    def generate(self, system: str, user: str) -> str: ...
```

Three concrete implementations live behind `get_llm_client()`:

**`GeminiClient`** — multi-key rotation, per-key cooldown on 429. Uses the
new `google-genai` SDK with one client per key (the old
`google-generativeai` SDK uses a global `genai.configure()` that cannot
rotate keys). If all keys are cooling down, raises a clear exception.

**`OllamaClient`** — talks to Ollama's OpenAI-compatible endpoint
(`OLLAMA_HOST`). Runs `qwen3:8b` by default. On CPU, 8–15 seconds per
generation.

**`FallbackLLMClient`** — wraps primary and fallback. Tries primary; on
**any** exception, logs `primary_llm_failed_falling_back_to_ollama` and
calls fallback.

**Key constraint:** Gemini free-tier rate limits are **per Google Cloud
project**, not per API key. Multiple keys in one project share one
20 req/day quota. Multi-key rotation only helps when keys come from
separate projects.

**Why the interface is frozen:** both orchestrators call
`llm_client.generate()` in two places each (query rewriting + final
answer). Extending the interface breaks four call sites silently. New
behavior (streaming, token counts) must be wrapped, not added.

---

## 9. Frontend

`frontend/app.py` is a **pure HTTP client** — it never imports `app.*`
and never touches Postgres. Four sections (Chat, Upload, Documents,
Settings). Session state (`st.session_state.session_id`) persists a UUID
across reruns so follow-up questions work.

**Why Streamlit:** the spec asks for "a simple web UI (Streamlit or
React)". Streamlit delivers a working UI in one file with zero build
step. The backend API is the boundary — replacing the frontend with
React or plain HTML requires no backend changes.

**Feedback:** 👍/👎 per answer, wired to `POST /feedback`. A "down" vote
opens an optional comment field before submitting.

---

## 10. Configuration Reference

All in `app/config.py`, loaded from `.env`. `config.py` is the **only**
module that reads `os.environ`.

```env
APP_ENV=local                LOG_LEVEL=INFO
MAX_UPLOAD_MB=25             UPLOAD_DIR=./data/uploads
DATABASE_URL=postgresql+psycopg://postgres:qwerty@localhost:5433/modern_rag

EMBEDDING_PROVIDER=local     EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384

LLM_PROVIDER=gemini_with_ollama_fallback
GEMINI_API_KEYS=key1,key2,key3
GEMINI_MODEL=gemini-2.5-flash
OLLAMA_MODEL=qwen3:8b
OLLAMA_HOST=http://host.docker.internal:11434

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

**Hidden latency trap:** `sentence-transformers` checks huggingface.co
for model updates on load by default. In a container with no outbound
DNS, this retries 5 times and adds ~10–30 s to the first query. Fix:
`HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` in the backend's
environment. These are set.

---

## 11. Error Handling

`RagPlatformError` is the base class. `main.py` has one
`@app.exception_handler(RagPlatformError)` converting any subclass to a
clean 400 JSON body. `IngestionError` carries a `document_id` so the
pipeline can mark **that specific document** `FAILED` without crashing
the background task.

**Never raise bare `Exception`.** Never return a stack trace to the
client. Log the trace, return the domain error.

**Never log secrets.** The convention is `extra=` never contains file
contents, request bodies, or API keys. This is a hard rule, not a
guideline.

---

## 12. Versioning & Migrations

Schema is managed by Alembic. Revision `0001` documents the baseline
schema as it existed after Phases 1–4, built incrementally via
`create_all()` and ad-hoc DDL before Alembic was introduced.

**On an existing database, `alembic stamp head`** — this marks the DB as
already being at revision `0001` without executing the CREATE TABLE
statements (which would fail on an existing schema).

**From this point forward:**
```bash
# Edit a model in backend/app/db/models.py, then:
docker compose exec backend alembic revision --autogenerate -m "description"
# Review the generated file in backend/alembic/versions/
docker compose exec backend alembic upgrade head
```

**No more silent `create_all()` drift.** The reason Alembic was adopted:
`create_all()` only ever adds new tables, silently doing nothing when an
existing table needs a new column. That caused a real bug —
`chunks.content_tsv` was missing after a schema change, discovered only
when a query crashed.

---

## 13. Known Design Tensions

Three points where the design is not obviously "correct" — documented
so future contributors understand the trade-offs rather than rediscovering
them:

**Two abstention gates vs. one.** The improved pipeline abstains both
after retrieval and after compression. This produces two log paths for
"abstained" but reflects reality: either stage can empty the candidate
set for legitimate reasons. Merging them would hide which stage failed.

**Rewrite failure is silent.** When `rewrite_query` errors, the pipeline
logs a warning and uses the original question. This means a bad LLM day
produces subtly worse retrieval, not a visible error. The trade-off is
correct (fail open beats fail closed for a retrieval step) but makes
diagnosis harder. If rewriting becomes a frequent source of problems,
add a metric.

**`MAX_UPLOAD_MB` is enforced before parsing, not streaming.** A client
that lies about `Content-Length` could theoretically send more data than
the limit allows. FastAPI's default behavior and Docker's memory limits
make this hard to exploit at demo scale. Production should stream-limit.
```

---

**3 of 6 delivered.** Reply **"next"** for `TASKS.md`.