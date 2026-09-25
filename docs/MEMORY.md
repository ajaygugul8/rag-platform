Here's the complete `docs/MEMORY.md`. Save at `docs/MEMORY.md`.

```markdown
# Project Memory - Modern RAG Platform

**Purpose:** context for the next human or AI agent picking up this
codebase. Read this first. It captures decisions, war stories, and open
threads that are not obvious from the code.

**Last updated:** 2026-09-25

**Companion docs:** `../HLD.md` (architecture, decisions, phase status),
`../LLD.md` (module detail, schemas, API contracts),
`ARCHITECTURE.md` (deeper module layout),
`RULES.md` (invariants and landmines).

---

## 1. What This Is

An internal knowledge assistant built as a **demonstration** of the full
modern-RAG stack - not a toy. The headline requirement is a **head-to-head
comparison of a baseline pipeline vs. an improved pipeline** on the same
evaluation set. Everything else serves that comparison.

**Verified state:** 23 automated tests passing; 20-question golden set
eval run cleanly with baseline 0.83 and improved 0.94 retrieval hit rate.

---

## 1.5 Multimodal Ingestion

The pipeline handles three chunk modalities, all persisted with
`chunks.modality`:

| modality | source | chunk content |
|---|---|---|
| `text` | Docling TextItem / SectionHeaderItem / ListItem, merged by section | paragraph prose |
| `table` | Docling TableItem, serialized via `export_to_markdown()` | markdown table (never split by row) |
| `image` | Docling PictureItem, described by moondream:1.8b | `Alternate text for this image: ...` + `This image depicts: ...` |

**Key structural markers:** every image chunk starts with `"Alternate
text for this image"` or `"This image depicts"`. Retrieval code uses
these prefixes to identify image chunks without needing a schema change
on `RetrievedChunk` (which is a lightweight dataclass with no modality
field).

**Three retrieval fixes for the modality gap:**

1. `hybrid.hybrid_search()` multiplies image chunk scores by 2.5 when the
   query contains an image keyword (chart/image/figure/diagram/photo/
   graph/illustration/screenshot). Applied *before* sorting and slicing
   so a low-scoring image chunk can rise into the top-k.
2. `improved_rag.answer_query()` — if rerank drops all image chunks for
   an image query, it splices the best image candidate back into the
   final set.
3. The raw-cosine abstention gate relaxes from 0.6 to 0.35 when the
   query contains an image keyword AND an image candidate exists.

**Prompt rule 5** makes document-supplied alt text authoritative over the
machine-generated vision description. Without this, moondream's imprecise
descriptions leak into answers verbatim (it called a "screen reader market
share" pie chart "operating systems used by various companies").

**DOCX alt text extraction.** Docling does NOT populate
`PictureItem.caption_text` for DOCX. python-docx's `inline_shapes`
attribute misses floating images (returned 0 for `sample3.docx`). The
extractor walks the raw XML for `wp:docPr` elements:

```python
_WP_DOCPR_NS = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr"
alts = [dp.get("descr") for dp in doc.element.body.iter(_WP_DOCPR_NS)]
```

**Do not remove these four fixes.** They're load-bearing for image
retrieval and they're additive — text-only queries skip all of them.

---

## 2. Current State

| Phase | Status |
|---|---|
| 1 Foundation | Done |
| 2 Baseline RAG | Done |
| 3 Retrieval upgrades | Done |
| 4 Advanced RAG | Done |
| 5 Evaluation | Done (20-question run, numbers below) |
| 6 Hardening | Partial — Alembic, feedback, Gemini+Ollama, per-stage tracing all done; Redis, task queue, per-user auth deferred |
| 7 Demo packaging + multimodal | Done — Streamlit, README, docs, Docling, tables, images |

**Eval numbers (latest 20-question run):**

| Metric | baseline | improved |
|---|---:|---:|
| hit_rate | 0.83 | 0.94 |
| MRR | 0.81 | 0.94 |
| keyword_coverage | 0.81 | 0.89 |
| abstention_accuracy | 0.85 | 0.95 |
| avg latency | 71ms | 1698ms |

**What works today (verified manually, real Docker deployment):**
- Multi-format ingestion (PDF / DOCX / TXT / MD)
- Text, table, and image chunks all retrievable through the same pipeline
- Hybrid retrieval + reranking
- Conversation-aware query rewriting with "return unchanged" rule
- Multi-query expansion
- Abstention on off-corpus questions and LLM-level refusals
- Response caching (stateless hits, session-scoped bypasses)
- Streamlit frontend: upload → chat → citations → feedback
- `POST /feedback` writes to DB
- Gemini multi-key + Ollama fallback
- Alembic revisions 0001 (baseline), 0002 (modality + parent_chunk_id)
- 23 passing tests (run inside the container)

**What does not work:**
- PDF images are not always detected as `PictureItem` (depends how the PDF encodes them)
- moondream:1.8b occasionally mislabels image subjects (mitigated by prompt rule 5)
- Scanned PDFs produce no extractable text (no OCR layer)
- Word tables: some edge cases are skipped (owner has identified the cause; not yet fixed)

---

## 3. Environment - Hard-Won Facts

### 3.1 Port collision: Postgres on 5432 (Windows)
A **native Windows PostgreSQL** (`postgres.exe`) and **Docker's port
forwarder** (`com.docker.backend.exe`) both bound `0.0.0.0:5432`.
Windows handed connections non-deterministically - sometimes to the
container, sometimes to the native install. Symptoms seen:
- `password authentication failed for user "rag"` (native DB has no `rag` user)
- `type "vector" does not exist` (native DB has no pgvector)

**Resolution:** Docker's Postgres is mapped to host port **5433** in
`docker-compose.yml`. `.env`'s `DATABASE_URL` uses `localhost:5433`. The
backend container still talks to `postgres:5432` internally (via the
compose-level `environment:` override), so nothing inside Docker changed.

**If you hit this again:**
```bash
netstat -ano | findstr :5432
Get-Process -Id <pid>
```
Two listeners on one port is the tell.

### 3.2 `.env` location and CWD
`config.py` loads `.env` from the repo root. Running `pytest` from
`backend/` used to silently fall back to defaults (which pointed at
`localhost:5432` with the wrong credentials). The path has since been
resolved relative to `__file__`, but the general rule stands: run
repo-root-relative commands from the repo root.

### 3.3 Enum casing
`DocumentStatus` is defined **lowercase** in Python
(`DocumentStatus.READY`) but stored **uppercase** in Postgres
(`READY`). Any raw SQL must use uppercase labels:

```sql
-- YES
DELETE FROM documents WHERE status='FAILED';
-- NO - "invalid input value for enum document_status: failed"
DELETE FROM documents WHERE status='failed';
```

### 3.4 `docker-compose.yml` `version:` warning
The top-level `version: "3.9"` key is obsolete. Harmless, but noisy on
every compose command.

### 3.5 PowerShell `-Form` doesn't exist in PS 5.1
Windows PowerShell 5.1 (the default on many machines) has no
`Invoke-RestMethod -Form`. Use `curl.exe` with `-F`, and for JSON form
fields use `<file.json` to avoid quoting hell:

```powershell
$metaJson = '{"department":"hr"}'
$metaJson | Out-File -Encoding ascii -NoNewline .\meta_tmp.json
curl.exe -X POST "http://localhost:8000/documents" `
  -H "Authorization: Bearer change-me-dev-token" `
  -F "file=@C:\path\to\file.pdf" `
  -F "metadata=<meta_tmp.json"
```

### 3.6 Git Bash vs PowerShell vs WSL
Three different shells exist on Windows. Commands written for one fail
in the others:

- **Git Bash:** prompt contains `MINGW64`; paths use `/c/Users/...`
- **PowerShell:** prompt contains `PS`; paths use `C:\Users\...`; line
  continuation is backtick
- **WSL:** prompt is `user@host:/mnt/c/...`; **does not see Git repos**
  the same way; different filesystem boundary

If `docker compose` complains about a missing file, you're probably in
the wrong shell or directory.

### 3.7 Windows Application Control blocks host-side pytest
Running `pytest` on the Windows host fails with:

```
ImportError: DLL load failed while importing _argkmin:
An Application Control policy has blocked this file.
```

Root cause: Docling pulls in `transformers`, which pulls in
`scikit-learn`, whose compiled `_argkmin.pyd` gets blocked by Windows
Smart App Control or an enterprise WDAC policy.

**Fix: run tests in Docker instead.**
```bash
docker compose exec backend pytest -v
```
The container is Linux. No such policy. Same environment the app runs
in. This is the canonical test command from now on.

### 3.8 HuggingFace offline flags
`sentence-transformers` checks huggingface.co on model load by default -
in a container without outbound DNS, that retries 5x and adds 10-30s
per query. Setting `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`
prevents this. **But** Docling also uses HF to fetch its layout models.
On the *first* run (fresh `hf_cache` volume), the offline flag blocks
Docling's download and you get `OfflineModeIsEnabled`. The fix is:

1. Temporarily set `HF_HUB_OFFLINE=0`, `TRANSFORMERS_OFFLINE=0`
2. Run one parse to populate the cache
3. Flip back to `1`

After the first parse, models live in the persistent `hf_cache` volume
and the offline flag is safe.

### 3.9 Duplicate documents in the DB
There is **no uniqueness constraint on `documents.filename`**. Upload
the same file twice → two rows. Re-running the eval with `--keep-data`
accumulates rows. This pollutes retrieval (4 copies of the same content
in the top-k).

**Cleanup query** (keeps the newest copy per filename):
```sql
WITH ranked AS (
    SELECT id, filename,
           ROW_NUMBER() OVER (PARTITION BY filename ORDER BY created_at DESC) AS rn
    FROM documents
)
DELETE FROM documents WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
```

### 3.10 PII in the corpus
**Every document in the DB is visible to anyone with the API token.**
A personal bank statement was accidentally uploaded during testing at
one point and had to be deleted. **Before committing, before demoing,
before pushing**, verify the corpus contains only documents you're
willing to expose:

```sql
SELECT filename FROM documents ORDER BY created_at DESC;
```

---

## 4. Design Decisions Worth Knowing

1. **Two orchestrators, not one with flags.** Required by the spec's
   baseline-vs-improved comparison. `naive_rag.py` and `improved_rag.py`
   are separate modules.
2. **Abstention is gated on raw cosine, not fused score, not reranker
   score.** Explained at length in `improved_rag.py`.
3. **Rerank reorders; it does not gate.** Applying a threshold to
   `bge-reranker-base` output vetoed a correctly-ranked match (0.0056).
4. **Metadata filtering is JSONB containment**, not a fixed schema.
5. **Config lives in one file.** `app/config.py` is the only module that
   reads `os.environ`.
6. **Ingestion failures never crash the request.** Every stage is
   wrapped; a bad file marks `documents.status = FAILED` with a reason.
7. **`LLMClient` interface is frozen.** Both orchestrators call it.
8. **Frontend is a pure HTTP client.** `frontend/app.py` never imports
   `app.*`.
9. **Alembic, not `create_all()`.** `create_all()` only adds new tables;
   it silently does nothing when an existing table needs a new column.
10. **Tables are never split.** One table = one chunk.
11. **Image alt text is authoritative over vision descriptions.**
12. **Image chunks are structurally identifiable by content prefix.**
    Retrieval code uses `chunk.content.startswith(...)` instead of a
    schema field, keeping retrieval decoupled from chunking.

---

## 5. War Stories - Bugs Found and How

### 5.1 The dedup no-op
`deduplicate()` used Jaccard on 5-word shingles at threshold 0.8. True
Jaccard between a chunk and its suffix is capped at `|shorter|/|longer|`,
which stays below 0.8 for realistic near-dups. **Fix:** containment
(`|A∩B| / min(|A|,|B|)`) with a length-ratio guard (`> 2.0` → not a dup).

### 5.2 The meta-tensor pitfall
`NotImplementedError: Cannot copy out of meta tensor; no data!` on first
use of the local embedding model or reranker. Root cause: newer
`transformers`/`accelerate` load via a "meta device" placeholder that
needs a clean download. **Fix:** `device="cpu"` +
`low_cpu_mem_usage=False`, plus a persistent `hf_cache` volume. Do not
remove.

### 5.3 The rerank-threshold bug
`improved_rag.py` filtered reranked chunks with `score >= 0.15`. The
cross-encoder output is not calibrated 0-1 - a correctly-ranked
vocabulary-mismatched query scored **0.0056**. **Fix:** removed the
filter. Abstention gates upstream on raw cosine.

### 5.4 The min-max normalization trap
`hybrid.py` normalizes scores per query. That guarantees the best
candidate is near 1.0 even when the whole set is irrelevant.
**Lesson:** normalized scores are good for *ranking*, useless for *gating*.

### 5.5 The LLM-abstention flag bug
Orchestrators hardcoded `abstained=False` on the final return even when
the LLM echoed the abstention message. **Fix:** reconcile the flag with
the LLM output — `abstained = ABSTENTION_MESSAGE.lower() in answer_text.lower()`.

### 5.6 The query-rewrite over-eagerness
`rewrite_query` injected context from prior turns into standalone
questions. After "What is the market size in the SmartHome Hub
document?" a follow-up query "What was the PDF market share in 2020
according to the table?" got rewritten to include "in the SmartHome Hub
document?" - wrong document, false abstention.

**Two-part fix:**
1. Prompt rule — "return UNCHANGED if already standalone" with
   counter-examples.
2. Safety net — the raw-cosine gate computes the max of the resolved
   query and the original question relevance.

### 5.7 The 73-second latency anomaly
Session-scoped query took ~73s vs ~2.3s for stateless. Root cause:
Gemini free-tier 503 responses + SDK exponential backoff. Add HF offline
env vars to prevent additional retries; accept 3-12s variance on free
tier.

### 5.8 Gemini quota is per project, not per key
Creating three API keys inside one project gives 20 req/day total, not
60. All keys return the same 429. **To actually get 60/day, each key must
come from a separate Google Cloud project.**

### 5.9 The metadata-filter gate leak
`improved_rag._retrieve` and the safety net both called `vector_search`
without `metadata_filters`. A query scoped to `department=hr` could pass
the raw-relevance gate using a chunk from `department=engineering`.
**Fix:** pass `metadata_filters` to both calls.

### 5.10 DOCX alt text wasn't extracted
Docling does not populate `caption_text` for DOCX. python-docx's
`inline_shapes` misses floating images (returned 0 for `sample3.docx`).
**Fix:** walk the raw XML for `wp:docPr` elements — catches both inline
and floating images.

### 5.11 The modality gap
"Chart" queries returned text chunks *about* charts, not the actual
chart image chunk. The cross-encoder, trained on text-text pairs, has no
concept of "image chunk." **Three-part fix:**
1. `hybrid_search`: boost image chunks x2.5 when query has image keyword
2. `improved_rag`: after rerank, splice the best image candidate back
3. `improved_rag`: relax raw-cosine gate to 0.35 for image queries with
   an image candidate

### 5.12 moondream mislabeled a chart
moondream:1.8b called a "screen reader market share" pie chart "operating
systems used by various companies." The LLM repeated it verbatim — the
pipeline was correct, the vision model was wrong. **Fix:** prompt rule 5
makes document-supplied alt text authoritative.

### 5.13 Streamlit `st.session_state` in a background thread
The progress UI runs the HTTP query in a Python thread so the spinner
stays responsive. Reading `st.session_state.pipeline` from inside that
thread raised `AttributeError: st.session_state has no attribute
"pipeline"`. **Root cause:** `st.session_state` is bound to the script
execution context, not the OS thread.

**Fix:** capture `pipeline`, `session_id`, `api_token` on the main
thread, pass them as function arguments to the thread, return results
via a shared dict. The thread never touches `st.session_state`.

### 5.14 `st.columns([1, 0])` crashes
`st.columns` requires all widths to be positive integers. Zero is not
valid. The header used `st.columns([1, 0])` as a "no right text"
fallback, which crashed on every page without a right-side text.
**Fix:** render the title directly via `st.markdown` when there's no
right text; only use `st.columns` when there are two things to show.

### 5.15 Streamlit CSS HTML rendering
`st.markdown(html, unsafe_allow_html=True)` treats any line with 4+
leading spaces as a code block. Indented HTML blocks (from
triple-quoted f-strings) rendered as literal text. **Fix:** all HTML in
`frontend/app.py` uses single-line string concatenation, no leading
whitespace.

### 5.16 CSS specificity vs Streamlit defaults
Streamlit applies `!important` to its own button styling inside
`[data-testid="stHorizontalBlock"]`. Custom button overrides must ALSO
use `!important` or they lose silently. This bit the back-button rule
once. **Rule:** any button override in this project uses `!important`
on every property.

### 5.17 Windows Application Control blocks pytest
See §3.7. Run tests in Docker.

---

## 6. Multi-Query - What It Does and Does Not Do

Directly verified: `expand_queries("PTO accrual amount")` returns
variants that all contain **"PTO"**, none reach **"paid annual leave"**.
Multi-query improves **syntactic** recall; it does not bridge **domain
vocabulary**. The LLM bridges residual gaps at generation time.

**Performance note:** `ENABLE_MULTI_QUERY=true` triples retrieval work
(1 expansion call + N hybrid searches). For demos, leave it `false` -
cuts ~20s off every improved-pipeline query with minimal quality loss.

---

## 7. Threshold Calibration

`RAW_VECTOR_MIN_RELEVANCE_SCORE = 0.6` (shared by both pipelines).

Measured against this corpus + `bge-small-en-v1.5`:
- Relevant question: **0.84**
- "What is the company's stock price?": **0.50**
- "What is the capital of France?": **0.38**

Small sentence-embedding models suffer **anisotropy** - unrelated English
clusters with a similarity floor above zero. 0.6 sits above both noise
samples and below real signal. **3 data points is not rigorous.** Revisit
once the Phase 5 eval set gives true-positive/true-negative pairs.

---

## 8. Gotchas for the Next Agent

1. **`pipeline` enum is `baseline | improved`** - not `naive`.
2. **`resolved_query` is only set when rewriting fires** (i.e., when
   conversation history exists).
3. **Improved abstains at three points.** "Abstained" does not always
   mean "retrieval found nothing."
4. **`EMBEDDING_DIM` is baked into the schema.** Changing the model is a
   migration, not a config edit.
5. **The `hf_cache` volume is load-bearing.** Removing it re-triggers
   the meta-tensor bug and forces Docling model re-downloads.
6. **`test_phase4_advanced.py` imports through the orchestrator**, which
   drags in the DB. Pure-function tests should import from
   `retrieval.compression` and `retrieval.query_transform` directly.
7. **Postgres is on 5433 on the host, 5432 inside Docker.**
8. **`frontend/app.py` is a client only.** Do not import `app.*`.
9. **`abstained` is set in three places.** A UI must show the same thing
   for all three.
10. **`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are required** after
    the first model download.
11. **Image chunks are structurally identifiable** by their content
    prefix. Retrieval code uses this instead of a schema field.
12. **The three modality fixes are additive.** Text-only queries skip all
    three code paths.
13. **Run pytest in Docker, not on the Windows host.**
14. **Never put `.env` in git.** Verify `git check-ignore .env` before
    every commit.
15. **Check the corpus for PII before every demo or push.**

---

## 9. Key File Locations

| What | Where |
|---|---|
| Config (single env reader) | `backend/app/config.py` |
| Abstention logic | `backend/app/orchestrator/{naive_rag,improved_rag}.py` |
| Hybrid fusion + modality boost | `backend/app/retrieval/hybrid.py` |
| Reranker | `backend/app/retrieval/reranker.py` |
| Dedup + budget | `backend/app/retrieval/compression.py` |
| Query rewrite + multi-query | `backend/app/retrieval/query_transform.py` |
| Prompt + rule 5 | `backend/app/generation/prompt.py` |
| LLM provider factory | `backend/app/generation/providers.py` |
| Vision (image description) | `backend/app/generation/vision.py` |
| Parsers (Docling) | `backend/app/ingestion/parsers.py` |
| Ingestion pipeline | `backend/app/ingestion/pipeline.py` |
| Chunking (text, tables) | `backend/app/ingestion/chunking.py` |
| Schema | `backend/app/db/models.py` |
| Migrations | `backend/alembic/versions/` |
| Eval harness | `eval/run_eval.py` |
| Golden dataset | `eval/golden_dataset.json` |
| Frontend | `frontend/app.py` |
| Docker compose | `docker-compose.yml` |

---

## 10. Next Session - Exact Starting Point

1. **Verify the corpus is clean.** No PII. No duplicate documents.
   ```sql
   SELECT filename, COUNT(*) FROM documents GROUP BY filename;
   ```
2. **Confirm tests still pass.**
   ```bash
   docker compose exec backend pytest -v
   ```
3. **Confirm the eval still reproduces.**
   ```bash
   python eval/run_eval.py
   # expected: baseline 0.83, improved 0.94
   ```
4. **Pick from the four remaining tasks** (in this order):
   - Fix the Word table extraction edge case (owner has identified the cause)
   - Decide on image display (inline vs. linked)
   - Test concurrent users
   - Write `docs/WALKTHROUGH.md`
5. **Do not touch:**
   - `device="cpu"` / `low_cpu_mem_usage=False` kwargs
   - Rerank threshold filter (there shouldn't be one)
   - Abstention gate on raw cosine
   - Prompt rule 5
   - The `wp:docPr` alt-text extractor

---

## 11. Honest Self-Assessment

**Strengths:** clean modular architecture; two real pipelines; multimodal
ingestion (text + tables + images) with all three chunk types retrievable
through the same pipeline; abstention that behaves correctly on the demo
corpus; the rationale for every non-obvious choice is written down;
grounded answers with citations across formats; 23 passing tests; a real
evaluation with a real improvement margin.

**Weaknesses:** moondream is imprecise (mitigated by prompt rule 5, not
fixed); PDF image detection is incomplete; free-tier LLM latency is
unpredictable; no per-user auth; no concurrent-user testing; no load
testing; no OCR; some Word table edge cases skip.

**What matters next:** finish the four remaining tasks (Word table fix,
image display decision, concurrent testing, walkthrough doc). Everything
else is either already done or explicitly out of scope.

**Lesson from this build:** every non-obvious fix in section 5 exists
because a plausible-looking simplification turned out to be wrong. The
`device="cpu"` kwargs look like cruft. The "return unchanged" rule looks
redundant with the OR-gate. The raw-cosine threshold looks overkill next
to the fused score. Each is load-bearing. **Read the war stories before
removing anything.**
```

---

Save at `docs/MEMORY.md`, then commit:

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
git add docs/MEMORY.md README.md
git commit -m "Docs: refresh README and MEMORY for agent handoff"
git push
```

Both files now stand alone as handoffs. An agent or engineer can read `README.md` first, then `docs/MEMORY.md`, and know exactly what the system does, why it's built this way, and what not to break.