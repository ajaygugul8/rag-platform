Here's the complete `docs/TASKS.md`. Save at `docs/TASKS.md`.

```markdown
# Task Tracker - Modern RAG Platform

**Legend:** ✅ done · ⚠️ done with caveats · 🔄 in progress · ⏳ not started

**Last updated:** 2026-09-25

---

## Phase 1 - Foundation ✅

- [x] Repo scaffold, `docker-compose.yml`, `.env.example`
- [x] `config.py` - single source of env vars (only module reading `os.environ`)
- [x] Postgres + pgvector with `init.sql`
- [x] `POST /documents` with validation, auth, background ingestion
- [x] `GET /documents`, `GET /documents/{id}`, `GET /health`
- [x] Bearer-token auth dependency (`app/core/security.py`)
- [x] Unit tests: upload validation, auth, CRUD

---

## Phase 2 - Baseline RAG ✅

- [x] PDF / DOCX / TXT / MD parsers (`ingestion/parsers.py`)
- [x] Cleaning - normalize whitespace, preserve headings
- [x] Fixed + recursive chunking strategies
- [x] Local embeddings (`bge-small-en-v1.5`, 384-dim)
- [x] `chunks` table with generated `content_tsv`, HNSW index
- [x] `vector_search()` with configurable top-k
- [x] `naive_rag.answer_query()` - retrieve → prompt → generate
- [x] Grounded prompt with citation enforcement (`generation/prompt.py`)
- [x] Unit + integration tests

---

## Phase 3 - Retrieval Upgrades ✅

- [x] `keyword_store.py` - Postgres full-text (`ts_rank_cd`)
- [x] `hybrid.py` - min-max normalized fusion, `alpha` configurable
- [x] `metadata.py` - JSONB containment filter
- [x] `reranker.py` - `bge-reranker-base` cross-encoder
- [x] `improved_rag.py` - hybrid + rerank pipeline
- [x] `pipeline` query parameter to A/B compare baseline vs. improved
- [x] **Verified end-to-end on real Docker** - multi-document,
      multi-format retrieval; correct source routing; correct
      abstention; DOCX section-title extraction; rerank ordering

---

## Phase 4 - Advanced RAG ✅

- [x] `query_transform.py::rewrite_query()` - conversation-aware
- [x] `query_transform.py::expand_queries()` - multi-query expansion
- [x] `compression.py::compress_context()` - dedup + budget selection
- [x] `conversation/history.py` + `conversation_turns` table
- [x] `session_id` on `POST /query`
- [x] Response cache (`core/cache.py`), bypassed when `session_id` present
- [x] **Verified:** rewriting (`resolved_query` correct on follow-ups)
- [x] **Verified:** multi-query fires (`expand_queries` returns 4 variants)
- [x] **Verified:** caching (stateless hits; session-scoped bypasses)
- [x] **Verified:** abstention gate on raw cosine (0.6)
- [x] **Fixed:** LLM-level abstention flag reconciliation
- [x] **Fixed:** query rewrite over-eagerness ("return UNCHANGED" rule added)
- [x] **Fixed:** rewrite safety net - gate considers original question
- [x] **Fixed:** dedup no-op (Jaccard → containment + length-ratio guard)

---

## Phase 5 - Evaluation ✅

- [x] Golden dataset (`eval/golden_dataset.json`) - **20 questions**
      across 7 categories
- [x] Sample corpus (`eval/sample_corpus/`) - 5 documents
- [x] Harness (`eval/run_eval.py`) - runs both pipelines, computes
      metrics, writes JSON + Markdown report
- [x] Report regenerator (`eval/regenerate_report.py`)
- [x] **Ran end-to-end** with 20-question golden set. Latest results:

  | Metric | baseline | improved | Δ |
  |---|---:|---:|---:|
  | hit_rate | 0.83 | **0.94** | +0.11 |
  | MRR | 0.81 | **0.94** | +0.13 |
  | keyword_coverage | 0.81 | **0.89** | +0.08 |
  | abstention_accuracy | 0.85 | **0.95** | +0.10 |
  | avg latency | **71 ms** | 1698 ms | +1627 ms |

- [x] Corpus scoping via `document_ids` - user uploads cannot contaminate
      the benchmark
- [x] Markdown encoding fix applied (0-byte `.md` bug resolved)

---

## Phase 6 - Production Hardening ⚠️

### Done
- [x] **Alembic migrations** - revisions `0001` (baseline) and `0002`
      (modality + parent_chunk_id)
- [x] **`POST /feedback`** endpoint
- [x] **Gemini multi-key rotation** with per-key cooldown on 429
- [x] **Ollama fallback** for rate-limited / offline operation
- [x] **HF offline env vars** (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`)
- [x] **Per-stage tracing** - every orchestrator stage wrapped in
      `trace_stage`
- [x] **Token usage logging** - `llm_usage` events with prompt/completion/total
- [x] **Retrieval result logging** - `retrieval_results` with candidate counts
      and score range
- [x] **HTTPBearer security scheme** - `/docs` Authorize button works
- [x] **Streamlit frontend** - upload, chat, citations, feedback

### Deferred (documented as out-of-scope for the demo)
- [ ] Redis cache - replace in-process `core/cache.py` before `--workers > 1`
- [ ] Task queue (Celery/RQ/arq) - replace `BackgroundTasks` for parallel ingestion
- [ ] Real auth (per-user tokens, per-document ACLs) - one shared token by design
- [ ] Load testing - no concurrent-user benchmark has been run

---

## Phase 7 - Demo Packaging + Multimodal ✅

### Multimodal ingestion
- [x] **Docling 2.14** for PDF/DOCX parsing (replaces pypdf/python-docx)
- [x] **Tables** serialized as markdown, one chunk per table, never split
- [x] **Images** described by `moondream:1.8b` via Ollama
- [x] **DOCX alt text** extracted via `wp:docPr` XML walk
- [x] `chunks.modality` column (`text` / `table` / `image`)
- [x] `chunks.parent_chunk_id` column (plumbing for future parent/child)
- [x] `_merge_text_units()` - consecutive text units merged by section

### Retrieval fixes for modality gap
- [x] Modality boost in `hybrid_search` (×2.5 for image chunks on image queries)
- [x] Modality guarantee after rerank (splice best image candidate back)
- [x] Modality-aware gate relaxation (0.6 → 0.35 for image queries)

### Generation fixes
- [x] Prompt rule 5 - alt text authoritative over vision descriptions

### Frontend
- [x] Streamlit app rewritten with light theme + amber accent
- [x] Multi-stage progress indicator (background thread, thread-safe)
- [x] Navigation moved to top of sidebar
- [x] DeepSeek-style chat input
- [x] Fixed `st.session_state` thread-safety bug
- [x] Fixed `st.columns([1, 0])` crash
- [x] Removed fake "Copy" button
- [x] Fixed uppercase labels → sentence case

### Documentation
- [x] `README.md` - setup, config, usage, architecture, limitations
- [x] `HLD.md` - architecture, decisions, phase status
- [x] `LLD.md` - module detail, schemas, API contracts
- [x] `docs/ARCHITECTURE.md` - deeper module layout
- [x] `docs/DESIGN.md` - why every choice was made
- [x] `docs/MEMORY.md` - war stories, gotchas
- [x] `docs/RULES.md` - invariants and landmines
- [x] `docs/PRD.md` - this document set
- [x] `docs/TASKS.md` - this file

---

## Phase 8 - Post-Demo ⏳

- [ ] **Fix Word table extraction edge case** - some Word tables are
      skipped entirely. Cause identified by owner; fix pending.
      Location: `ingestion/parsers.py`, Docling `TableItem` detection.
- [ ] **Decide on image display** - inline `<img>` render vs. link to
      source. If inline: add an authenticated image-serving route,
      include URL or base64 in query response for image citations.
- [ ] **Test concurrent users** - 10 parallel queries via locust or
      ThreadPoolExecutor. Watch for cache corruption and ingestion
      blocking.
- [ ] **Write `docs/WALKTHROUGH.md`** - single short "start here" doc
      for a new engineer's first hour.
- [ ] **Optional:** Redis cache, task queue, per-user auth.

---

## Known Bugs (prioritized)

| # | Severity | Bug | Location | Status |
|---|---|---|---|---|
| 1 | Medium | Word table extraction skips some tables | `ingestion/parsers.py` | Open - cause known |
| 2 | Medium | Image display not rendered in citations | `frontend/app.py` `render_sources()` | Open - decision pending |
| 3 | Low | Duplicate documents possible (no filename uniqueness) | Schema | Documented, manual cleanup |
| 4 | Low | PDF images not always detected as PictureItems | Docling behavior | Documented limitation |
| 5 | Low | Vision descriptions occasionally mislabel subjects | moondream:1.8b | Mitigated by prompt rule 5 |
| 6 | Low | Multi-query doesn't bridge domain vocabulary | Design | Documented limitation |

---

## Definition of Done (per feature)

A feature is done when:

1. Code is written, typed, and logged (structured, no secrets)
2. Unit tests cover pure logic; integration covers the flow
3. `ARCHITECTURE.md` / `DESIGN.md` updated if interfaces changed
4. `MEMORY.md` updated with any new gotcha or decision
5. Verified against a running Docker deployment - not just pytest

---

## Test Suite Status

```
docker compose exec backend pytest -v
# 23 passed
```

**Coverage:**
- `test_documents.py` - upload validation, auth, CRUD, health (5 tests)
- `test_chunking.py` - fixed/recursive chunking (3 tests)
- `test_hybrid.py` - score normalization, metadata filter (5 tests)
- `test_phase3_hybrid_retrieval.py` - baseline vs. improved (2 tests)
- `test_phase3b_tables.py` - table chunks retrievable (1 test)
- `test_phase4_advanced.py` - dedup, budget, rewrite (5 tests)
- `test_query_e2e.py` - full upload → ingest → query flow (2 tests)

**Not covered by automated tests:**
- Reranker correctness under pytest (verified manually)
- Multi-query expansion
- Cache under concurrent requests
- Eval harness itself
- Tracing output correctness
- Vision description quality
- Concurrent-user behavior

---

## Spec Acceptance Criteria

From the original requirements PDF §10:

- [x] A new document can be uploaded, processed, and queried without
      manual database intervention
- [x] Questions return answers grounded in the uploaded knowledge base
      with traceable citations
- [x] The system demonstrates both semantic and keyword-based retrieval
      and a reranking stage
- [x] The system handles follow-up questions and at least one
      difficult/ambiguous query pattern
- [x] The assistant abstains when relevant evidence is unavailable
- [x] An evaluation script can be run repeatedly and produces measurable
      retrieval and generation metrics
- [x] The complete demo can be started from documented instructions on a
      clean development environment

**All seven acceptance criteria met.**

---

## Next Session - Start Here

1. Verify the corpus is clean (no PII, no duplicates)
2. Confirm tests still pass:
   ```bash
   docker compose exec backend pytest -v
   ```
3. Confirm the eval still reproduces:
   ```bash
   python eval/run_eval.py
   ```
4. Pick from Phase 8 tasks in priority order
5. Do not touch: `device="cpu"` kwargs, rerank threshold filter
   (there shouldn't be one), raw-cosine abstention gate, prompt rule 5,
   `wp:docPr` alt-text extractor
```

---

Save at `docs/TASKS.md`, then commit:

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
git add docs/TASKS.md docs/PRD.md docs/DESIGN.md docs/MEMORY.md README.md
git commit -m "Docs: add PRD, TASKS, DESIGN; refresh MEMORY and README"
git push
```