Here's the complete `docs/DESIGN.md`. Save at `docs/DESIGN.md`.

```markdown
# Detailed Design - Modern RAG Platform

**Companion docs:** `ARCHITECTURE.md` (system-level layout),
`RULES.md` (invariants and landmines),
`MEMORY.md` (war stories),
`../HLD.md` (decisions and phase status),
`../LLD.md` (schemas and API contracts).

This document explains *why* the system is built the way it is - the
reasoning behind the algorithms, the trade-offs, and the failure modes
each choice exists to prevent. For "how to use" and "what not to touch",
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
| `status` | enum | `UPLOADED / PROCESSING / READY / FAILED` (stored **uppercase** in Postgres) |
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

**No uniqueness constraint on `filename`.** Uploading the same file twice
creates two rows. This is intentional - it lets users re-upload a revised
version without deleting the old one. It also means duplicate cleanup is
a manual operation (see `MEMORY.md` §3.9).

### 1.2 `chunks`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `document_id` | UUID FK, `ON DELETE CASCADE` | |
| `content` | text | |
| `chunk_index` | int | order within document |
| `page_number` | int, nullable | from PDF parsing |
| `section_title` | varchar(512), nullable | from heading detection |
| `token_count` | int | `words × 1.3` (approximate) |
| `modality` | varchar(16) | `'text'` / `'table'` / `'image'`; default `'text'` |
| `parent_chunk_id` | UUID, nullable, self-FK | links image/table chunks back to surrounding text |
| `chunk_metadata` | JSONB | e.g. `{"chunking_strategy": "recursive", "image_path": "..."}` |
| `embedding` | `vector(384)` | nullable until ingestion completes |
| `content_tsv` | `tsvector` **generated**, persisted | Postgres-maintained |
| `created_at` | timestamptz | |

Indexes:
- btree on `document_id` (`ix_chunks_document_id`)
- **GIN** on `content_tsv` (`ix_chunks_content_tsv`)
- btree on `modality` (`ix_chunks_modality`)
- **HNSW** (`vector_cosine_ops`) on `embedding` — created at app startup,
  not via SQLAlchemy `Index()`, because pgvector's index DDL is not
  expressible that way.

**Why HNSW, not ivfflat:** ivfflat needs pre-existing data to build a
useful index (it clusters existing vectors). HNSW builds incrementally
and works from an empty table — which matters for a demo that starts
empty and gets progressively populated.

**Why `content_tsv` is a generated column:** it must always reflect
`content`, and the app should never write to it. Postgres computes it on
insert and update. If you change `content`, `tsv` follows automatically.

**Why `token_count` is approximate:** `word_count × 1.3` is a rough but
cheap proxy. Accurate enough for the compression budget
(`CONTEXT_TOKEN_BUDGET`) but not for billing or hard context-window
limits. Swap `approx_token_count` for `tiktoken` if either becomes a
requirement.

**Why `modality` is a string not an enum:** adding a new modality (e.g.
`"audio"`) later shouldn't require a migration to extend an enum. String
comparison is enough for the retrieval-side logic, which mostly checks
`chunk.content.startswith(...)` anyway (see §6.5).

**Why `parent_chunk_id` exists but is currently unused:** it's
plumbing for future parent/child retrieval - retrieve a precise child
chunk, return the larger parent context. The column is in place so a
future feature doesn't need a migration. Do not remove it just because
nothing writes to it yet.

### 1.3 `conversation_turns`

`id, session_id (client-generated), role ("user"|"assistant"), content,
created_at`. Indexed on `(session_id, created_at)`. Only
`conversation/history.py` reads it.

**Why client-generated `session_id`:** no server-side session management
needed. The frontend generates a UUID, sends it with each query, and the
backend treats it as an opaque string. No auth check on it — the bearer
token is the only auth boundary.

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

A 2 MB / 50-page PDF takes 5–20 seconds to parse, clean, chunk, and
embed. With image descriptions it can take 60+ seconds. Making the upload
response wait for that blocks a worker for the duration.

FastAPI's `BackgroundTasks` runs ingestion after the response is sent.
The client polls `GET /documents/{id}` until `READY`.

**Limitation:** `BackgroundTasks` runs in-process, single-worker. If the
API process restarts mid-ingestion, that document stays stuck in
`PROCESSING`. Production fix: Celery/RQ/arq. For a demo, restart-tolerant
statuses + polling are sufficient.

### 2.2 Parsers (Docling for PDF/DOCX)

| Format | Parser | Extracts | Notes |
|---|---|---|---|
| **PDF** | Docling | text, page numbers, tables, images | Images not always classified as `PictureItem` — depends how the PDF encodes them |
| **DOCX** | Docling | text, headings, tables, images | Alt text extracted via a supplementary `wp:docPr` XML walk |
| **TXT** | plain read | text | no structure |
| **MD** | plain read | text | treats markdown headings as text |

**Why Docling, not pypdf/python-docx:** Docling returns typed elements
(`TextItem`, `SectionHeaderItem`, `ListItem`, `TableItem`, `PictureItem`),
which is exactly the abstraction this pipeline needs. pypdf and
python-docx give flat strings. With Docling, one parse call produces all
three chunk types.

**Cost:** Docling pulls PyTorch (~800 MB) and downloads its layout models
(~500 MB) on first use. Build time increased from 1 minute to 8 minutes;
first-parse time from 2 seconds to 3 minutes. Subsequent parses are 30–90
seconds. These are one-time or per-document costs, not per-query.

**Trade-off:** a much heavier ingestion path, in exchange for handling
tables and images as first-class content rather than losing them.

### 2.3 Chunking strategies

**Fixed:** sliding window over `text.split()` by word count, `step =
chunk_size - overlap`.

**Recursive (default):** split on `\n\n` paragraph boundaries;
accumulate paragraphs into a buffer until adding the next would exceed
`chunk_size` tokens; flush. A single oversized paragraph falls back to
fixed-size splitting for just that paragraph.

**Why recursive is the default:** paragraphs are semantically coherent
units. Splitting mid-paragraph loses context. Splitting at paragraph
boundaries keeps each chunk self-contained while honoring a size cap.

**Tables: one chunk per table, never split.** Splitting a table by rows
destroys the association between a value and its column header. `Q4
2023 | $2,180` is meaningless when separated from `Revenue | Return
Rate`. The whole table goes into one chunk, serialized as markdown.

**Images: one chunk per image, containing alt text + vision
description.** Content format:

```
Alternate text for this image: <if document supplies it>

This image depicts: <vision model description>
```

The alt text comes first because it's authoritative (see §6.4). The
`"This image depicts"` prefix is a structural marker retrieval code uses
to identify image chunks (see §6.5).

### 2.4 Merging consecutive text units

Docling emits one element per paragraph, heading, and list item. Fed
directly to the chunker, each becomes a ~15-token chunk with a weak
embedding. A 26-chunk document became a 26-chunk document with no
substantive chunks.

**Fix:** `_merge_text_units()` concatenates consecutive units that share
the same `section_title` into a single `ParsedUnit`. The recursive
chunker then splits by paragraph as designed.

**Effect (verified on `sample3.docx`):** text chunks went from 26 to 9.
Average tokens went from 15 to 44. Substantive section-sized chunks
instead of per-paragraph fragments.

**Why section boundaries matter:** a new `section_title` flushes the
buffer. This keeps the heading as the first line of its section's
content, not mixed with unrelated preceding text.

### 2.5 Cleaning

Whitespace normalization, trailing-space stripping. **Headings and
structure are preserved** — cleaning does not flatten them. This is what
makes section-title extraction possible downstream.

---

## 3. Retrieval Algorithms

### 3.1 Hybrid fusion

```
candidate_k = top_k * candidate_multiplier     # default 3
v = vector_search(candidate_k)                 # cosine similarity
k = keyword_search(candidate_k)                # ts_rank_cd

v_norm = min_max_normalize(v)                  # empty → {}; all-equal → 1.0
k_norm = min_max_normalize(k)

for id in (v_norm ∪ k_norm):
    combined = alpha * v_norm.get(id, 0) + (1-alpha) * k_norm.get(id, 0)

# Modality boost (before sorting)
if query contains image keyword:
    for chunk in blended:
        if chunk.content starts with image-chunk prefix:
            chunk.score *= 2.5

sort by combined score, return top_k
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
not a bug - normalization is relative to the batch. It's why the fused
score is unsuitable as an abstention gate.

### 3.2 Modality boost

When the query contains an image keyword (`chart|image|figure|diagram|
photo|graph|illustration|screenshot`), image chunks get a ×2.5 boost
*before* the top-k slice. This is the first of three fixes for the
"modality gap" (see §6.3).

**Why before the slice:** an image chunk that scored 20th in the raw
candidate pool could rise into the top-8 with the boost, but only if the
boost is applied before sorting and slicing. Applying it after would
have no effect.

### 3.3 Keyword search

Postgres full-text — `content_tsv` (generated column) with `ts_rank_cd`.
GIN index. Chosen over Elasticsearch because it delivers the same
lexical-matching value at this scale with zero extra infrastructure.

### 3.4 Metadata filter

`build_metadata_filter({"department": "hr"})` compiles to a JSONB
containment check: `Document.doc_metadata @> '{"department":"hr"}'::jsonb`.
Multiple keys are ANDed. No migration needed when a new filterable field
appears.

**Known bug fixed during development:** `improved_rag._retrieve` and the
safety net both called `vector_search` without passing
`metadata_filters`, so a filter on `department=hr` could still score
against `department=engineering` chunks. The filter now passes through
every retrieval call.

### 3.5 Reranking

`CrossEncoder("BAAI/bge-reranker-base").predict([(query, chunk), ...])`,
lazily loaded once per process (`@lru_cache`), forced to `device="cpu"`
with `low_cpu_mem_usage=False`.

Scores **replace** the chunk's existing `.score` entirely (not blended).
By the time reranking runs, the hybrid score has already done its job —
picking the candidate pool. The cross-encoder score is what orders the
final answer's citations.

**Critical empirical finding:** `bge-reranker-base` scores are **not
calibrated 0–1**. For a vocabulary-mismatched query ("PTO accrual
amount" vs. corpus text "paid annual leave"), the cross-encoder
correctly ranked the right chunk #1 **but scored it 0.0056**. Applying
a `>= 0.15` filter silently vetoed a genuinely correct match.

**Resolution:** reranking **reorders, never gates.** Abstention is
gated upstream on raw cosine.

### 3.6 Vector search

pgvector HNSW, `vector_cosine_ops`, `EF_SEARCH` at default. Query-time
cost is negligible at this scale (< 50k chunks). At larger scale, tune
`ef_search` or move to a dedicated vector DB — the API doesn't change.

---

## 4. Contextual Compression

Two passes, both cheap (no LLM calls — this runs after reranking, right
before prompt construction).

### 4.1 Deduplication

**Current implementation:** containment (`|A∩B| / min(|A|,|B|)`) on
5-word shingles, threshold 0.8, with a length-ratio guard
(`max/min > 2.0 → not a duplicate`).

**Why containment, not Jaccard:** the pattern this function needs to
catch is "one chunk is essentially a subset of another" — an
overlapping window that got slightly more text on one side. Jaccard
penalizes length differences, which is the wrong behavior. True Jaccard
between a chunk and its suffix is capped at `|shorter| / |longer|`,
which for realistic near-dups stays below 0.8 — the original Jaccard@0.8
implementation was effectively a no-op.

**Why the length-ratio guard:** pure containment would flag a tiny
heading chunk as a duplicate of a large chunk that happens to contain
its words. The guard prevents that.

### 4.2 Budget selection

Greedily keep highest-scored, deduplicated chunks until `token_budget`
(`CONTEXT_TOKEN_BUDGET`, default 2000). Oversized single chunks are kept
only if nothing else has been selected — better one large chunk than
abstain.

**Why greedy, not knapsack:** greedy is O(n) and the chunks are already
sorted by score. Knapsack would pack more tokens for the same budget but
at the cost of both complexity and unpredictability — the prompt would
change based on the shape of the whole batch, making eval numbers
noisier.

---

## 5. Abstention — the Core Design Constraint

Three score types flow through the pipeline. Only one is safe to gate on.

| Score | Range | Property | Gate-safe? |
|---|---|---|---|
| Raw vector cosine | [0, 1] absolute | calibrated similarity | ✅ |
| Hybrid fused | [0, 1] per-query | min-max normalized | ❌ always tops near 1.0 |
| Cross-encoder | unbounded | not calibrated | ❌ correct match can score 0.005 |

**The rule:** abstention gates on **raw cosine of the resolved
question**.

### 5.1 Why raw cosine

Raw cosine is the only score that is *absolute* — it means the same
thing for every query, independent of what else was retrieved.
Empirical calibration on this corpus (`bge-small-en-v1.5`):

- Relevant question: **0.84**
- "What is the company's stock price?": **0.50**
- "What is the capital of France?": **0.38**

Small sentence-embedding models suffer from **anisotropy** — generic
English text clusters together in embedding space, producing a
similarity floor well above 0 for unrelated content. 0.6 sits above both
noise samples and below real signal.

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

### 5.4 Three-stage gating in the improved pipeline

The improved pipeline performs **three** abstention checks:

1. **After retrieval** — raw cosine of resolved query below 0.6, or no
   candidates at all
2. **After compression** — empty chunk set
3. **After generation** — the LLM echoed `ABSTENTION_MESSAGE`

All three are legitimate refusals. `abstained=True` means any of them.
Reading improved-pipeline logs, "abstained" does not always mean
"retrieval found nothing."

### 5.5 The rewrite safety net

If `rewrite_query` produced a different query, the improved pipeline
computes raw cosine for **both** the resolved query and the original
question, and takes the max. This closes the "rewrite injected context
and pointed retrieval at the wrong document" failure mode — even if the
LLM corrupts the query, retrieval still sees the user's actual words.

### 5.6 Modality-aware gate relaxation

For queries that explicitly ask about an image, when an image chunk
exists in the candidate pool, the raw-cosine threshold relaxes from 0.6
to 0.35. This is the third of the three "modality gap" fixes (see §6.3).

**Why this is safe:** the relaxation only fires when two conditions are
both true — (1) the query contains an image keyword and (2) an image
chunk is present in the pool. A text-only query never triggers it. An
off-corpus image query with no image chunks in the pool never triggers
it. The gate for the general case is unchanged.

---

## 6. Multimodal Handling

### 6.1 The three-modality architecture

Text, tables, and images all become text chunks with a `modality` tag.
The retrieval and generation layers never know the difference — they
operate on text. Only ingestion and the prompt assembly know about
modalities.

**Why this works:** an image's description is text. A table's markdown is
text. Once both are text, `bge-small-en-v1.5` embeds them like any other
chunk. No multimodal embedding model needed.

**What this doesn't do:** cross-modal retrieval. You cannot search for
images *with* images, or find documents that contain a specific visual
layout. That would require a multimodal embedder (Jina v4, CLIP) and a
different retrieval path. Not implemented — not needed for
natural-language queries about text-like content.

### 6.2 Why Docling

Docling returns typed elements. That's the entire reason it was chosen
over pypdf/python-docx. The alternative would have been a parser
per modality (pdfplumber for text, a table-detection library for
tables, PDF image extraction for images), plus glue code to align them.
Docling gives all three in one pass with a unified coordinate system.

### 6.3 The modality gap

**Observation:** a query for "what does the chart show?" retrieves text
chunks that *discuss* charts, not the chart image chunk. Text-only
embeddings don't naturally distinguish "content that is a chart" from
"content that mentions charts."

**Why:** the cross-encoder is trained on text-text pairs. It has no
concept of "this chunk is an image." Given two chunks — one saying
"this chapter presents datasets commonly found in PDF reports" and one
saying "This image depicts: a pie chart showing..." — the cross-encoder
scores the first higher for the query "what does the chart show?" because
it's a better prose match. The second chunk's structured prefix
(`This image depicts:`) doesn't match query vocabulary.

**Three additive fixes:**

1. **Modality boost in `hybrid_search`** — image chunks score ×2.5 when
   the query mentions an image. Applied before the top-k slice.
2. **Modality guarantee in `improved_rag`** — after rerank, if the query
   mentions an image and no image chunk survived, splice the
   highest-scoring image candidate back into the final set. Replaces the
   weakest reranked chunk to keep `top_n` stable.
3. **Modality-aware gate relaxation** — the abstention threshold drops
   from 0.6 to 0.35 for image queries when an image candidate exists.

**Why all three and not just one:** each addresses a different stage of
the pipeline. The boost helps retrieval. The guarantee helps reranking.
The relaxation helps abstention. Without all three, an image query
either doesn't retrieve the right chunk, or retrieves it and then loses
it to rerank, or retrieves it and passes it to rerank and then gets
vetoed by the gate.

**Verified:** `"What does the chart show?"` on `sample3.docx` returns
the pie-chart image chunk with alt text *"Chart of Screen Reader Market
Share"* as its top citation.

### 6.4 Alt text authority (prompt rule 5)

moondream:1.8b correctly identifies images but can mislabel their
subject. It called a "screen reader market share" pie chart "operating
systems used by various companies." The LLM repeated the mislabel
verbatim — the pipeline behaved correctly, the vision model was wrong.

**Fix:** the SYSTEM_PROMPT has 5 rules. Rule 5 is:

> When a source contains both "Alternate text for this image:" and
> "This image depicts:", the alternate text is authoritative. The
> description is machine-generated and may be imprecise. Use the
> description only to supplement, never to contradict.

**Why this works:** alt text is written by the document author. It's the
ground truth. The vision description is a machine guess. When both
exist, the author wins.

**When alt text doesn't exist:** the description is the only signal.
Errors propagate. Documented as a known limitation. Upgrade path:
`qwen2.5-vl:7b` (4.7 GB, ~30–60s/image on CPU, noticeably better at
chart comprehension).

### 6.5 Structural modality detection

Retrieval code does not have a `modality` field on `RetrievedChunk` (the
lightweight dataclass returned by `vector_search` / `hybrid_search`).
Instead, image chunks are identified by content prefix:

```python
_IMAGE_CHUNK_PREFIXES = ("Alternate text for this image", "This image depicts")
is_image = chunk.content.startswith(_IMAGE_CHUNK_PREFIXES)
```

**Why not add `modality` to `RetrievedChunk`:** it would require a
schema change to a low-level dataclass, plus every SQL query that
constructs a `RetrievedChunk` would need to select the new column.
Instead, image chunks are self-identifying by construction — the content
format is guaranteed by `_build_image_chunks`.

**Trade-off:** if the content format changes, this detection breaks.
The prefix is a contract. There's no runtime enforcement; it's a
convention. Documented in `RULES.md`.

### 6.6 DOCX alt text extraction

Docling does not populate `PictureItem.caption_text` for DOCX.
python-docx's `inline_shapes` misses floating images (returned 0 for
`sample3.docx`, which has two images).

**Fix:** walk the raw XML for `wp:docPr` elements:

```python
_WP_DOCPR_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
alts = [dp.get("descr") for dp in doc.element.body.iter(_WP_DOCPR_NS)]
```

**Why this works:** `wp:docPr` is the DrawingML container for every
image — inline or floating. Walking the element tree catches both.

**Alignment with Docling's picture units:** alt texts are applied in
document order. If the counts don't match (Docling found a different
number of images than python-docx), the alt texts are skipped and a
warning is logged. Best-effort, not guaranteed.

---

## 7. Query Transformation

### 7.1 `rewrite_query`

Triggered only when conversation history exists. The LLM converts a
follow-up ("what about sick leave?") into a standalone query ("What is
the sick leave policy?"). **Fails open** — any LLM error returns the
original question unchanged.

**Design rule (from a real bug):** the prompt must permit "return
unchanged." An earlier version said only "resolve it into a fully
standalone question using that context" — with no instruction to leave
standalone questions alone. That caused a real bug: after a turn about
the SmartHome Hub document, a new standalone question ("What was the PDF
market share in 2020 according to the table?") got rewritten to "...in
the SmartHome Hub document?" — injecting a topic never mentioned,
pointing retrieval at the wrong document, causing a false abstention.

The prompt now includes:
- Explicit "return UNCHANGED if already standalone" rule
- Counter-examples showing standalone questions that must not be rewritten
- "Do not append context just because it appeared earlier"

The LLM's default bias is to include history whenever it's present. The
prompt has to fight that.

### 7.2 `expand_queries`

When `ENABLE_MULTI_QUERY=true`, generates up to 3 paraphrases of the
resolved question. Each is embedded and run through `hybrid_search`
independently; results merge by keeping the best score per `chunk_id`.

**Empirical limitation:** paraphrases preserve domain jargon. For "PTO
accrual amount", all variants contained "PTO" — none reached "paid
annual leave", the corpus's terminology. Multi-query improves
*syntactic* recall; it does not bridge *domain vocabulary*. The LLM
bridges the residual gap at generation time.

**Performance:** multi-query triples retrieval work (1 expansion call +
N hybrid searches). Leave `ENABLE_MULTI_QUERY=false` for demos; turn it
on for evaluation runs where latency doesn't matter.

---

## 8. Prompt Design

`SYSTEM_PROMPT` enforces five rules:

1. Answer **only** from the provided numbered sources.
2. **Cite** supporting sources in `[n]` format.
3. If the sources are insufficient, respond with the exact abstention
   message — do not guess.
4. Be concise; do not repeat the question.
5. **Alt text is authoritative over vision descriptions.** (See §6.4.)

`build_user_prompt(resolved_query, chunks, history)`:
- Includes prior conversation turns when present (for pronoun resolution)
- Numbers each chunk so citations map to a specific retrieved item
- Truncates chunk text to a bounded excerpt per chunk

The prompt is the **only** guard against hallucination after the
abstention gate passes. It is deliberately restrictive: better to abstain
than to answer from parametric knowledge.

**Post-generation reconciliation:** if the LLM outputs the abstention
message, the pipeline sets `abstained=True` — even if retrieval had
found candidates. This is the third abstention path.

---

## 9. LLM Provider Layer

The `LLMClient` interface is exactly:

```python
class LLMClient:
    def generate(self, system: str, user: str) -> str: ...
```

Three concrete implementations behind `get_llm_client()`:

**`_OpenAICompatibleClient`** — a thin wrapper around any OpenAI-compatible
endpoint. Gemini and Ollama both qualify — only `base_url`, `api_key`,
and `model` differ between instances.

**`FallbackLLMClient`** — wraps primary and fallback. Tries primary; on
**any** exception, logs `primary_llm_failed_falling_back_to_ollama` and
calls fallback.

**Provider chain:** `get_llm_client()` builds
`Gemini key 1 → Gemini key 2 → ... → Gemini key N → Ollama` by nesting
`FallbackLLMClient` N times. No multi-key-aware client class is needed.

**Key constraint:** Gemini free-tier rate limits are **per Google Cloud
project**, not per API key. Multiple keys in one project share one
20 req/day quota. Multi-key rotation only helps when keys come from
separate projects.

**Why the interface is frozen:** both orchestrators call
`llm_client.generate()` in multiple places (query rewriting,
multi-query expansion, final answer). Extending the interface breaks
every call site silently.

**Token usage logging:** every successful call logs `llm_usage` with
`prompt_tokens`, `completion_tokens`, `total_tokens` when the provider
exposes them. Silent no-op otherwise.

---

## 10. Vision Layer

`vision.py` is separate from `providers.py` on purpose. The
`LLMClient` interface is text-only by contract. Vision passes image
bytes alongside the prompt and needs its own small interface.

`describe_image(image_bytes) -> str` — sends the PNG to `moondream:1.8b`
via Ollama's OpenAI-compatible endpoint. Returns `""` on any failure;
ingestion never fails because one image couldn't be described.

**Token limit:** `VISION_MAX_TOKENS=60`. Long descriptions dilute the
embedding — a 70-word description averaging against a 5-word query
scores lower than a 15-word description. Terse is better.

**Upgrade path:** `qwen2.5-vl:7b` (4.7 GB, ~30–60s/image on CPU) has
noticeably better chart comprehension. Change `OLLAMA_VISION_MODEL` in
`.env` and re-ingest. Same code path.

---

## 11. Frontend

`frontend/app.py` is a **pure HTTP client** — it never imports `app.*`
and never touches Postgres.

**Design principles (from the module docstring):**
1. The answer is the product. Reading experience comes first.
2. Progress is visible. RAG takes 30–60s; the user sees what's happening.
3. Citations are first-class. Numbered margin notes, not a buried
   expander.
4. Empty states guide the user with one-click examples, not silence.
5. Navigation stays out of the way of the primary task.

**Why Streamlit:** the spec asks for "a simple web UI (Streamlit or
React)". Streamlit delivers a working UI in one file with zero build
step. The backend API is the boundary — replacing the frontend with
React or plain HTML requires no backend changes.

**Thread safety:** the multi-stage progress indicator runs the HTTP call
in a Python thread so the UI stays responsive. `st.session_state` is NOT
thread-safe. All values the thread needs (pipeline, session_id,
api_token) must be read on the main thread and passed in as arguments.

**HTML rendering:** every `st.markdown()` call that emits HTML uses
single-line string concatenation, never indented triple-quoted strings.
Streamlit treats 4+ leading spaces inside a markdown string as a code
block, which renders raw HTML as literal text.

**CSS specificity:** Streamlit applies `!important` to its own button
styling inside `[data-testid="stHorizontalBlock"]`. Custom button
overrides must ALSO use `!important` or they lose silently.

**Encoding:** the file is pure ASCII on purpose. Non-ASCII characters
(em dashes, curly quotes, unicode icons) in Python source have
repeatedly caused `UnicodeDecodeError`/`SyntaxError` on Windows when
saved by an editor that defaults to cp1252 instead of UTF-8. HTML
entities like `&#10003;` render identically in the browser with no
encoding risk.

---

## 12. Configuration Reference

All in `app/config.py`, loaded from `.env`. `config.py` is the **only**
module that reads `os.environ`.

```env
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

**Hidden latency trap:** `sentence-transformers` checks huggingface.co
for model updates on load by default. In a container with no outbound
DNS, this retries 5× and adds 10–30 s to the first query. Fix:
`HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1` in the backend's
environment. But Docling needs network on its first parse — see
`MEMORY.md` §3.8 for the sequencing.

---

## 13. Error Handling

`RagPlatformError` is the base class. `main.py` has one
`@app.exception_handler(RagPlatformError)` converting any subclass to a
clean 400 JSON body. `IngestionError` carries a `document_id` so the
pipeline can mark **that specific document** `FAILED` without crashing
the background task.

**Never raise bare `Exception`.** Never return a stack trace to the
client. Log the trace, return the domain error.

**Never log secrets.** The convention (not enforced in code) is that
`extra=` never contains file contents, request bodies, or API keys.

---

## 14. Versioning & Migrations

Schema is managed by Alembic. Two revisions:

- **`0001`** — baseline schema (documents, chunks, conversation_turns,
  feedback). Applied via `stamp head` on the existing dev database,
  since the tables already existed from `create_all()`.
- **`0002`** — added `chunks.modality` and `chunks.parent_chunk_id`, plus
  the `ix_chunks_modality` index.

**Going forward:**
```bash
# After editing a model in backend/app/db/models.py:
docker compose exec backend alembic revision --autogenerate -m "description"
# Review the generated file in backend/alembic/versions/
docker compose exec backend alembic upgrade head
```

**Why Alembic, not `create_all()`:** `create_all()` only ever adds new
tables, silently doing nothing when an existing table needs a new column.
That caused a real bug — `chunks.content_tsv` was missing after a schema
change, discovered only when a query crashed.

---

## 15. Known Design Tensions

Points where the design is not obviously "correct" — documented so
future contributors understand the trade-offs rather than rediscovering
them.

**Three abstention gates vs. one.** The improved pipeline abstains after
retrieval, after compression, and after generation. This produces three
log paths for "abstained" but reflects reality: any of the three stages
can legitimately produce a refusal. Merging them would hide which stage
failed.

**Rewrite failure is silent.** When `rewrite_query` errors, the pipeline
logs a warning and uses the original question. A bad LLM day produces
subtly worse retrieval, not a visible error. The trade-off is correct
(fail open beats fail closed for a retrieval step) but makes diagnosis
harder.

**Docling absorbs text adjacent to images.** Text that sits immediately
next to an image is sometimes classified as part of the figure region by
Docling's layout model. One paragraph in `sample3.docx` was affected. No
fix — the alt text carries the semantic content.

**Modality detection is convention-based.** Image chunks are identified
by content prefix, not a schema field. If the content format changes,
detection breaks silently. The prefix is a contract enforced only by
`_build_image_chunks` writing it.

**`parent_chunk_id` is unused.** The column exists for future
parent/child retrieval but nothing writes to it. Removing it would save
one column; keeping it costs nothing and prevents a future migration.

**`MAX_UPLOAD_MB` is enforced before parsing, not streaming.** A client
that lies about `Content-Length` could theoretically send more data than
the limit allows. FastAPI's default behavior and Docker's memory limits
make this hard to exploit at demo scale. Production should stream-limit.
```

---

Save at `docs/DESIGN.md`, then commit:

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
git add docs/DESIGN.md docs/MEMORY.md README.md
git commit -m "Docs: DESIGN.md, MEMORY.md, README.md refreshed for handoff"
git push
```