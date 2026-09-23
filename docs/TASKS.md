## `docs/TASKS.md`

Save at `docs/TASKS.md`.

```markdown
# Task Tracker — Modern RAG Platform

**Legend:** ✅ done · ⚠️ done with caveats · 🔄 in progress · ⏳ not started

**Last updated:** 2026-09-21

---

## Phase 1 — Foundation ✅

- [x] Repo scaffold, `docker-compose.yml`, `.env.example`
- [x] `config.py` — single source of env vars (only module reading `os.environ`)
- [x] Postgres + pgvector with `init.sql`
- [x] `POST /documents` with validation, auth, background ingestion
- [x] `GET /documents`, `GET /documents/{id}`, `GET /health`
- [x] Bearer-token auth dependency (`app/core/security.py`)
- [x] Unit tests: upload validation, auth, CRUD

---

## Phase 2 — Baseline RAG ✅

- [x] PDF / DOCX / TXT / MD parsers (`ingestion/parsers.py`)
- [x] Cleaning — normalize whitespace, preserve headings
- [x] Fixed + recursive chunking strategies
- [x] Local embeddings (`bge-small-en-v1.5`, 384-dim)
- [x] `chunks` table with generated `content_tsv`, HNSW index
- [x] `vector_search()` with configurable top-k
- [x] `naive_rag.answer_query()` — retrieve → prompt → generate
- [x] Grounded prompt with citation enforcement (`generation/prompt.py`)
- [x] Unit + integration tests

---

## Phase 3 — Retrieval Upgrades ✅

- [x] `keyword_store.py` — Postgres full-text (`ts_rank_cd`)
- [x] `hybrid.py` — min-max normalized fusion, `alpha` configurable
- [x] `metadata.py` — JSONB containment filter
- [x] `reranker.py` — `bge-reranker-base` cross-encoder
- [x] `improved_rag.py` — hybrid + rerank pipeline
- [x] `pipeline` query parameter to A/B compare baseline vs. improved
- [x] **Verified end-to-end on real Docker** — multi-document, multi-format
      retrieval; correct source routing; correct abstention; DOCX
      section-title extraction; rerank ordering

---

## Phase 4 — Advanced RAG ✅

- [x] `query_transform.py::rewrite_query()` — conversation-aware
- [x] `query_transform.py::expand_queries()` — multi-query expansion
- [x] `compression.py::compress_context()` — dedup + budget selection
- [x] `conversation/history.py` + `conversation_turns` table
- [x] `session_id` on `POST /query`
- [x] Response cache (`core/cache.py`), bypassed when `session_id` present
- [x] **Verified:** rewriting (`resolved_query` correct on follow-ups)
- [x] **Verified:** multi-query fires (`expand_queries` returns 4 variants)
- [x] **Verified:** caching (stateless hits; session-scoped bypasses)
- [x] **Verified:** abstention gate on raw cosine (0.6) — off-corpus
      abstains, on-corpus answers
- [x] **Fixed:** LLM-level abstention flag reconciliation
- [x] **Fixed:** query rewrite over-eagerness (injected prior topics into
      standalone questions); "return UNCHANGED" rule added
- [x] **Fixed:** rewrite safety net — gate considers original question's
      raw relevance alongside the resolved query
- [ ] **Open:** dedup is a near-no-op (Jaccard@0.8 cannot catch
      overlapping-window near-duplicates). Fix: containment metric +
      length-ratio guard

---

## Phase 5 — Evaluation ✅

- [x] Golden dataset (`eval/golden_dataset.json`) — 7 questions across
      6 categories
- [x] Sample corpus (`eval/sample_corpus/`) — 3 documents
- [x] Harness (`eval/run_eval.py`) — runs both pipelines, computes metrics,
      writes JSON + Markdown report
- [x] Report regenerator (`eval/regenerate_report.py`)
- [x] **Ran end-to-end.** Results:

  | Metric | baseline | improved | Δ |
  |---|---:|---:|---:|
  | hit_rate | 0.50 | **0.83** | +0.33 |
  | MRR | 0.50 | **0.83** | +0.33 |
  | keyword_coverage | 0.50 | **0.75** | +0.25 |
  | abstention_accuracy | 0.57 | **0.86** | +0.29 |
  | avg latency | **65 ms** | 1050 ms | +985 ms |

- [x] Corpus scoping via `document_ids` — user uploads cannot contaminate
      the benchmark
- [ ] **Open:** expand golden set to ~18 questions for tighter confidence
      intervals (7 questions → ±10 pp noise)
- [ ] **Open:** fix the markdown encoding bug in `run_eval.py` (first run
      produced a 0-byte `.md`; `regenerate_report.py` works around it)

---

## Phase 6 — Production Hardening ⚠️

### Done
- [x] **Alembic migrations** — stamped existing schema to `0001`; forward
      changes go through `revision --autogenerate`
- [x] **`POST /feedback`** endpoint (was table-only, no route)
- [x] **Gemini multi-key rotation** with per-key cooldown on 429
- [x] **Ollama fallback** (`qwen3:8b`) for rate-limited / offline operation
- [x] **HF offline env vars** (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`)
      — eliminates ~10s/query wasted on unreachable huggingface.co DNS
- [x] **Streamlit frontend** — upload, chat, citations, feedback buttons

### Deferred (documented as out-of-scope for the demo)
- [ ] Redis cache — `core/cache.py` is in-process, not thread-safe, breaks
      with `--workers > 1`
- [ ] Task queue (Celery/RQ/arq) — `BackgroundTasks` is single-worker
- [ ] Real auth (per-user tokens, per-document ACLs) — one shared token
      by design
- [ ] Per-stage tracing — `tracing.py` wraps only the whole query
      pipeline, not individual retrieval/rerank/generation stages
- [ ] Load testing — no concurrent-user benchmark has been run
- [ ] 73s latency anomaly — traced to Gemini free-tier 503 retries; the
      HF offline fix reduces the tail, but free-tier variance (3–12s per
      query) is inherent

---

## Phase 7 — Demo Packaging ⚠️

- [x] **README.md** — setup, config, usage, architecture, limitations,
      troubleshooting
- [x] **Streamlit frontend** — spec's "simple web UI" requirement
- [x] **`docs/`** — PRD, ARCHITECTURE, RULES, DESIGN, TASKS, MEMORY
- [ ] **Architecture diagram** as a standalone artifact (currently ASCII
      in `ARCHITECTURE.md`)
- [ ] **Demo scenario scripts** — automate the 7 PRD §11 scenarios as a
      runnable script with pass/fail summary
- [ ] **Optional:** deploy to a hosted environment (Oracle Cloud free
      tier is the only one with enough RAM for local models)

---

## Known Bugs (prioritized)

| # | Severity | Bug | Fix |
|---|---|---|---|
| 1 | Medium | Dedup no-op (Jaccard@0.8) | Containment metric + ratio guard |
| 2 | Medium | `run_eval.py` markdown encoding bug (0-byte `.md`) | Add `encoding="utf-8"` to `write_text` |
| 3 | Low | Heading-only chunks cited (e.g. `"Employee Handbook"`) | Min-token filter at ingestion |
| 4 | Low | Reranker top-1 can be the wrong chunk when query repeats entity name | Document; LLM cites correctly |
| 5 | Low | Duplicate `FAILED` document rows possible from seed runs | `DELETE FROM documents WHERE status='FAILED'` |
| 6 | Low | `test_phase4_advanced.py` imports via orchestrator (drags in DB) | Import pure functions directly |
| 7 | Low | Duplicated relevance constant in both orchestrators | Move to `config.py` as one shared value |

---

## Definition of Done (per feature)

A feature is done when:

1. Code is written, typed, and logged (structured, no secrets)
2. Unit tests cover pure logic; integration covers the flow
3. `ARCHITECTURE.md` / `DESIGN.md` updated if interfaces changed
4. `MEMORY.md` updated with any new gotcha or decision
5. Verified against a running Docker deployment — not just pytest

---

## Next Session — Start Here

1. Fix the `run_eval.py` markdown encoding bug (10 min)
2. Expand `golden_dataset.json` to ~18 questions (20 min)
3. Fix dedup — containment metric + length-ratio guard (30 min)
4. Re-run eval, confirm improved numbers hold or improve (5 min)
5. Build the demo scenario script (1 hr)
6. Optional: Oracle Cloud deployment (2–4 hrs, ARM capacity permitting)

---

## Spec Acceptance Criteria — Status

From the original requirements PDF, §10:

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

**All seven acceptance criteria met.** The project is functionally
complete.
```

---

**4 of 6 delivered.** Reply **"next"** for `MEMORY.md`.