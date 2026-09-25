Here's the complete `docs/PRD.md`. Save at `docs/PRD.md`.

```markdown
# Product Requirements Document - Modern RAG Platform

**Status:** Living document
**Owner:** Principal AI/ML Engineering
**Last updated:** 2026-09-25
**Companion docs:** `../HLD.md`, `../LLD.md`, `ARCHITECTURE.md`,
`DESIGN.md`, `RULES.md`, `TASKS.md`, `MEMORY.md`

---

## 1. Vision

An **internal knowledge assistant** that lets users upload a corpus of
company documents (policies, manuals, FAQs, technical specs) and ask
natural-language questions, receiving answers grounded in those documents
with traceable citations - and abstaining cleanly when the corpus does
not contain the answer.

The system is deliberately **more than a vector-search chatbot**. It
exists to demonstrate, on real data, the full modern-RAG stack:
structure-aware chunking, hybrid retrieval, cross-encoder reranking,
query transformation, contextual compression, **multimodal ingestion
(text + tables + images)**, evaluation, and observability. It is also
structured so the **baseline** and **improved** pipelines can be
compared head-to-head on the same evaluation set - that comparison is
the single most important artifact the project produces.

## 2. Target Users

| Persona | Need |
|---|---|
| **Knowledge worker** (HR, ops, support) | Ask "what is the leave policy?" and get a cited answer instead of searching PDFs |
| **New hire / onboarding** | Query the corpus with natural language, trust the citations, follow the source |
| **AI/ML engineer evaluating RAG** | Run the eval harness, compare pipelines, inspect traces and metrics |
| **Future maintainer** | Read the docs, understand the design trade-offs, extend without breaking invariants |

**Non-user:** external customers, untrusted internet users. This is an
*internal* tool. See §6 (Security).

## 3. Core Use Cases

1. **Direct factual Q&A** - "How many days of paid annual leave do
   employees get?" → answer + citation to `handbook.docx § Leave Policy`.
2. **Multi-document synthesis** - answer requires combining evidence from
   two or more files.
3. **Follow-up in conversation** - "What about sick leave?" after asking
   about leave → the system resolves the pronoun against conversation
   history before retrieval.
4. **Vocabulary mismatch** - "PTO accrual amount" when the corpus says
   "paid annual leave". Multi-query expansion generates paraphrases; the
   LLM bridges residual term mismatch at generation time.
5. **Table lookup** - "What is the response count for JAWS in the
   screen reader table?" → retrieves the markdown-serialized table.
6. **Image description** - "What does the chart in the document show?"
   → retrieves the image chunk (alt text + vision description).
7. **Out-of-corpus questions** - "What is the capital of France?" →
   abstain, do not hallucinate.
8. **Baseline vs. improved comparison** - the same question run through
   both pipelines, with metrics that show where the improved pipeline
   earns its keep.

## 4. Functional Requirements

| # | Requirement | Status |
|---|---|---|
| F1 | Upload PDF, DOCX, TXT, MD with validation (type, size) and metadata | ✅ Done |
| F2 | Extract text; preserve page/section where practical; handle failures gracefully | ✅ Done |
| F3 | Normalize content while preserving headings and structure | ✅ Done |
| F4 | Configurable chunk size/overlap; ≥1 structure-aware strategy | ✅ Done |
| F5 | Store document ID, filename, page/section, source, timestamps, chunk ID, filterable metadata | ✅ Done |
| F6 | Generate embeddings and store in a vector DB | ✅ Done (pgvector) |
| F7 | Vector similarity retrieval with configurable top-k | ✅ Done |
| F8 | Hybrid retrieval (vector + BM25-style keyword) | ✅ Done |
| F9 | Reranking via cross-encoder before generation | ✅ Done |
| F10 | Query rewriting / expansion; multi-query retrieval | ✅ Done |
| F11 | Context selection: dedupe, compress within token budget | ✅ Done (containment dedup + budget) |
| F12 | Grounded generation with citation-enforcing prompt | ✅ Done |
| F13 | Citations including document name, page/section, chunk | ✅ Done |
| F14 | Abstention on low-evidence queries | ✅ Done (three-stage gate) |
| F15 | Short-term conversation history, isolated from retrieval | ✅ Done |
| F16 | User feedback endpoint (useful / not useful) | ✅ Done (`POST /feedback`) |
| F17 | Repeatable evaluation harness with retrieval + answer metrics | ✅ Done (`eval/run_eval.py`) |
| F18 | Observability: latency, retrieval results, token usage, failures, no secrets | ✅ Done (per-stage tracing + token + retrieval logging) |
| F19 | Pluggable LLM provider with fallback | ✅ Done (Gemini multi-key + Ollama) |
| F20 | Web UI for upload, chat, citations, feedback | ✅ Done (Streamlit) |
| F21 | Versioned database schema migrations | ✅ Done (Alembic 0001, 0002) |
| F22 | **Multimodal ingestion** - tables as first-class chunks | ✅ Done (markdown, never split) |
| F23 | **Multimodal ingestion** - images as first-class chunks | ✅ Done (alt text + vision description) |
| F24 | Modality-aware retrieval (image queries route correctly) | ✅ Done (boost + guarantee + gate relaxation) |

## 5. Non-Functional Requirements

- **Modularity:** every stage (parsing, chunking, embedding, retrieval,
  rerank, compression, generation, orchestration) lives behind a narrow
  interface; swap one without touching callers.
- **Configurability:** environment-driven; `app/config.py` is the *only*
  module that reads `os.environ`.
- **Secrets:** never hard-coded. `.env` for local; gitignored.
- **Latency:** baseline ~70 ms warm, improved ~1700 ms on the demo corpus
  with warm caches. Free-tier LLM variance: 3–12 s per query.
- **Observability:** structured JSON logs on every stage; no file
  contents, request bodies, or API keys in `extra=`.
- **Reproducibility:** `docker compose up` from a clean checkout is the
  only setup step required.
- **Testing:** unit tests for pure logic; integration tests for
  upload→ingest→query. 23 tests passing.
- **Auth:** bearer token on all routes. Per-user ACLs are explicitly out
  of scope (see §8).

## 6. Security Model

**In scope:**
- Bearer-token auth on all `/documents`, `/query`, and `/feedback` routes.
- File-type allowlist enforced before any disk or DB write.
- Upload size cap via `MAX_UPLOAD_MB`.
- Metadata filters scoped via JSONB containment - no SQL injection surface.

**Explicitly out of scope (documented limitations):**
- Multi-user identity. **One shared token for the whole demo.** Every
  uploaded document is visible to anyone holding the token.
- Per-document ACLs.
- Rate limiting per user (the LLM endpoint is cost-sensitive).
- Encryption at rest (relies on the host filesystem / Postgres defaults).

**Operational rule:** never upload PII. The shared-token model means
anything in the corpus is readable by anyone with the token. This has
bitten the project once (a bank statement was accidentally uploaded
during testing). See `MEMORY.md` §3.10.

## 7. Success Metrics

Metrics are produced by the Phase 5 eval harness against
`eval/golden_dataset.json` (20 questions across 7 categories).

**Retrieval quality**
- `hit_rate@8` - fraction of questions where the expected source
  document appears in top-8 citations
- `MRR` - mean reciprocal rank of the expected source document
- `keyword_coverage` - fraction of expected keywords found in the answer
- Target: improved pipeline > baseline on all three.

**Abstention quality**
- `abstention_accuracy` - correct abstention on unanswerable questions +
  no false abstention on answerable ones
- Target: ≥ 0.90

**Performance**
- Average latency per pipeline
- Free-tier LLM variance tolerated up to 12 s per query
- Concurrent-user behavior: untested (see §10)

**Baseline vs. improved (measured 2026-09-25, 20-question set):**

| Metric | baseline | improved | Δ |
|---|---:|---:|---:|
| hit_rate | 0.83 | **0.94** | +0.11 |
| MRR | 0.81 | **0.94** | +0.13 |
| keyword_coverage | 0.81 | **0.89** | +0.08 |
| abstention_accuracy | 0.85 | **0.95** | +0.10 |
| avg latency | **71 ms** | 1698 ms | +1627 ms |

The improved pipeline is decisively better on quality at ~24× the
latency. The trade-off is documented and expected - the baseline does a
single vector search; the improved one does rewrite + multi-query +
hybrid + rerank + compression + generation.

## 8. Out of Scope

- Multi-tenant user accounts and per-user document ACLs.
- Horizontal scaling of the backend; a real task queue for ingestion.
- A production-grade React/Vue frontend (Streamlit satisfies the spec's
  "simple web UI").
- Elasticsearch / OpenSearch / a dedicated vector DB - Postgres +
  pgvector covers both roles at this scale.
- Fine-tuning embeddings or the reranker.
- Streaming generation.
- OCR for scanned PDFs.
- Cross-modal retrieval (searching images with images).
- Fine-tuned vision models.

## 9. Roadmap & Current Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: repo, config, Docker, DB, upload, auth, health | ✅ Done |
| 2 | Baseline RAG: parse → clean → chunk → embed → vector retrieve → generate | ✅ Done |
| 3 | Retrieval upgrades: metadata filter, hybrid, rerank, pipeline comparison | ✅ Done |
| 4 | Advanced RAG: query rewrite, multi-query, compression, conversation | ✅ Done |
| 5 | Evaluation: golden dataset + harness comparing baseline vs. improved | ✅ Done (20-question run) |
| 6 | Production hardening: Alembic, feedback, LLM providers, tracing | ⚠️ Partial - see §10 |
| 7 | Demo packaging + multimodal: Docling, tables, images, frontend, docs | ✅ Done |
| 8 | Post-demo: concurrent testing, image display decision, walkthrough doc | ⏳ Not started |

## 10. Known Issues (as of 2026-09-25)

### Functional
1. **Word table extraction edge case** - some Word tables are skipped
   entirely. Cause identified by owner; fix not yet applied.
2. **Image display in citations** - image chunks exist and are retrievable
   by description, but the actual PNG is not shown inline. Decision
   pending: inline render vs. link to source.
3. **Duplicate document rows** - no uniqueness constraint on
   `documents.filename`. Uploading the same file twice creates two rows.
   Cleanup is a manual query (documented in `MEMORY.md` §3.9).

### Multimodal limitations
4. **Vision descriptions are non-authoritative** - `moondream:1.8b`
   correctly identifies images but can mislabel subjects. Mitigated by
   prompt rule 5 (alt text wins). Upgrade path: `qwen2.5-vl:7b`.
5. **PDF images are not always detected** - depends how the PDF encodes
   them. The 50-page sample PDF yields 0 PictureItems despite containing
   charts.
6. **No OCR** - scanned PDFs (image-only pages) produce no extractable
   text.
7. **Image descriptions add 5–15 s per image at ingestion** on CPU.

### Production readiness
8. **Auth is one shared bearer token** - no per-user access control.
9. **Cache is not thread-safe** - `core/cache.py` is an in-process
   LRU+TTL. Breaks with `--workers > 1`. Swap for Redis before scaling.
10. **Ingestion is single-worker** - `BackgroundTasks` runs in the API
    process. Add a task queue before scaling ingestion.
11. **No concurrent-user testing** - untested behavior under parallel
    load.
12. **No load testing** - no latency benchmark beyond single-query p50.

### Environment
13. **Windows host pytest fails** with `DLL load failed while importing
    _argkmin`. Windows Application Control blocks a scikit-learn binary.
    Run tests in Docker instead (`docker compose exec backend pytest -v`).

## 11. Demo Scenarios (acceptance)

The finished demo must show:
- Direct factual Q&A with a clear supporting passage.
- Multi-document synthesis.
- Follow-up question that depends on the previous turn.
- Query benefiting from rewriting (jargon → corpus vocabulary).
- Query where hybrid retrieval or reranking changes the retrieved
  evidence.
- Table extraction from a multi-page PDF.
- Image description retrieval.
- Query with no supporting evidence → clean abstention.
- Side-by-side baseline vs. improved comparison using eval metrics.

**All nine scenarios verified end to end.**

## 12. Sign-Off Criteria

- [x] Document upload → processing → query, no manual DB work.
- [x] Grounded answers with traceable citations.
- [x] Semantic + keyword retrieval + reranking demonstrated.
- [x] Follow-up questions handled; ≥1 difficult/ambiguous query pattern handled.
- [x] Assistant abstains on insufficient evidence.
- [x] Eval script runs repeatedly and produces measurable retrieval + generation metrics.
- [x] Complete demo starts from documented instructions on a clean environment.
- [x] Web UI for upload, chat, and feedback.
- [x] Pluggable LLM with fallback (Gemini → Ollama).
- [x] Versioned schema migrations (Alembic).
- [x] Multimodal ingestion (text + tables + images).
- [x] 23 automated tests passing.
- [ ] Concurrent-user testing.
- [ ] Word table extraction edge case fixed.
- [ ] Image display decision made.
- [ ] Walkthrough doc for handoff.

## 13. Next Steps (post-demo)

In priority order:

1. **Fix the Word table extraction edge case.** Cause identified;
   apply the fix in `ingestion/parsers.py`. Small, contained change.
2. **Decide on image display.** Inline `<img>` render vs. link to
   source. If inline: add an authenticated image-serving route and
   include a URL or base64 payload in the query response for image
   citations.
3. **Test concurrent users.** Run 10 parallel queries via locust or a
   ThreadPoolExecutor script. Watch for cache corruption and ingestion
   blocking.
4. **Write `docs/WALKTHROUGH.md`.** A single short "start here"
   document for a new engineer's first hour.
5. **Optional production hardening** (documented in `HLD.md` §9):
   Redis cache, task queue, per-user auth.
```