# Product Requirements Document — Modern RAG Platform

**Status:** Living document
**Owner:** Principal AI/ML Engineering
**Last updated:** 2026-09-21
**Companion docs:** `../HLD.md`, `../LLD.md`, `ARCHITECTURE.md`, `DESIGN.md`, `RULES.md`, `TASKS.md`, `MEMORY.md`

---

## 1. Vision

An **internal knowledge assistant** that lets users upload a corpus of
documents (policies, manuals, FAQs, technical specs) and ask
natural-language questions, receiving answers grounded in those documents
with traceable citations — and abstaining cleanly when the corpus does not
contain the answer.

The system is deliberately **more than a vector-search chatbot**. It exists
to demonstrate, on real data, the full modern-RAG stack: structure-aware
chunking, hybrid retrieval, cross-encoder reranking, query transformation,
contextual compression, evaluation, observability, and safe abstention.
It is also deliberately structured so the **baseline** and **improved**
pipelines can be compared head-to-head on the same evaluation set — that
comparison is the single most important artifact the project produces.

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

1. **Direct factual Q&A** — "How many days of paid annual leave do employees get?" → answer + citation to `handbook.docx § Leave Policy`.
2. **Multi-document synthesis** — answer requires combining evidence from two or more files (e.g., leave policy in `handbook.docx` + accrual details in `leave_policy.txt`).
3. **Follow-up in conversation** — "What about sick leave?" after asking about leave → the system resolves the pronoun against conversation history before retrieval.
4. **Vocabulary mismatch** — "PTO accrual amount" when the corpus says "paid annual leave". Multi-query expansion generates paraphrases; the LLM bridges residual term mismatch at generation time.
5. **Out-of-corpus questions** — "What is the capital of France?" → abstain, do not hallucinate.
6. **Table extraction** — "What was the PDF market share in 2020 according to the table?" → retrieve a specific row from a 50-page PDF's table.
7. **Baseline vs. improved comparison** — the same question run through both pipelines, with metrics that show where the improved pipeline earns its keep.

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
| F11 | Context selection: dedupe, compress within token budget | ⚠️ Done but dedup is near-no-op — see §10 |
| F12 | Grounded generation with citation-enforcing prompt | ✅ Done |
| F13 | Citations including document name, page/section, chunk | ✅ Done |
| F14 | Abstention on low-evidence queries | ✅ Done |
| F15 | Short-term conversation history, isolated from retrieval | ✅ Done |
| F16 | User feedback endpoint (useful / not useful) | ✅ Done (`POST /feedback`) |
| F17 | Repeatable evaluation harness with retrieval + answer metrics | ✅ Done (`eval/run_eval.py`) |
| F18 | Observability: latency, retrieval results, token usage, failures, no secrets | ⚠️ Log-based only; per-stage tracing partial |
| F19 | Pluggable LLM provider with fallback | ✅ Gemini multi-key + Ollama fallback |
| F20 | Web UI for upload, chat, citations, feedback | ✅ Streamlit (`frontend/app.py`) |
| F21 | Versioned database schema migrations | ✅ Alembic, stamped to 0001 |

## 5. Non-Functional Requirements

- **Modularity:** every stage (parsing, chunking, embedding, retrieval, rerank, compression, generation, orchestration) lives behind a narrow interface; swap one without touching callers.
- **Configurability:** environment-driven; `app/config.py` is the *only* module that reads `os.environ`.
- **Secrets:** never hard-coded. `.env` for local; `.env.example` in git.
- **Latency:** baseline ~65 ms, improved ~1050 ms on the demo corpus with warm caches. Free-tier LLM variance: 3–12 s per query.
- **Observability:** structured JSON logs on every stage; no file contents, request bodies, or API keys in `extra=`.
- **Reproducibility:** `docker compose up` from a clean checkout is the only setup step required.
- **Testing:** unit tests for pure logic; integration tests for upload→ingest→query.
- **Auth:** bearer token on all routes. Per-user ACLs are explicitly out of scope (see §8).

## 6. Security Model

**In scope:**
- Bearer-token auth on all `/documents`, `/query`, and `/feedback` routes.
- File-type allowlist enforced before any disk or DB write.
- Upload size cap via `MAX_UPLOAD_MB`.
- Metadata filters scoped via JSONB containment — no SQL injection surface.

**Explicitly out of scope (documented limitations):**
- Multi-user identity. **One shared token for the whole demo.** Every uploaded document is visible to anyone holding the token.
- Per-document ACLs.
- Rate limiting per user (the LLM endpoint is cost-sensitive).
- Encryption at rest (relies on the host filesystem / Postgres defaults).

## 7. Success Metrics

Metrics produced by the Phase 5 eval harness against `eval/golden_dataset.json`.

**Retrieval quality**
- `hit_rate@k` — fraction of questions where the expected source document appears in top-k citations
- `mrr` — mean reciprocal rank of the expected source document
- `keyword_coverage` — fraction of expected keywords found in the generated answer
- Target: improved pipeline > baseline on all three.

**Abstention quality**
- `abstention_accuracy` — correct abstention on unanswerable questions + no false abstention on answerable ones
- Target: ≥ 0.85

**Performance**
- Average latency per pipeline
- p95 latency under sustained load (not yet measured)

**Baseline vs. improved (measured 2026-09-21):**

| Metric | baseline | improved | Δ |
|---|---:|---:|---:|
| hit_rate | 0.50 | **0.83** | +0.33 |
| MRR | 0.50 | **0.83** | +0.33 |
| keyword_coverage | 0.50 | **0.75** | +0.25 |
| abstention_accuracy | 0.57 | **0.86** | +0.29 |
| avg latency | **65 ms** | 1050 ms | +985 ms |

The improved pipeline is decisively better on quality at 16× the latency.
The trade-off is documented and expected — the baseline does a single
vector search; the improved one does rewrite + multi-query + hybrid + rerank
+ compression + generation.

## 8. Out of Scope

- Multi-tenant user accounts and per-user document ACLs.
- Horizontal scaling of the backend; a real task queue for ingestion.
- A production-grade React/Vue frontend (Streamlit satisfies the spec's "simple web UI").
- Elasticsearch / OpenSearch / a dedicated vector DB — Postgres + pgvector covers both roles at this scale.
- Fine-tuning embeddings or the reranker.
- Streaming generation.
- Multi-modal ingestion (images, tables-as-images).
- OCR for scanned PDFs.

## 9. Roadmap & Current Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: repo, config, Docker, DB, upload, auth, health | ✅ Done |
| 2 | Baseline RAG: parse → clean → chunk → embed → vector retrieve → generate | ✅ Done |
| 3 | Retrieval upgrades: metadata filter, hybrid, rerank, pipeline comparison | ✅ Done |
| 4 | Advanced RAG: query rewrite, multi-query, compression, conversation | ✅ Done |
| 5 | Evaluation: golden dataset + harness comparing baseline vs. improved | ✅ Done |
| 6 | Production hardening: Alembic, feedback endpoint, pluggable LLM | ⚠️ Partial — Alembic ✅, feedback ✅, Gemini+Ollama ✅; Redis/task-queue/real-auth deferred |
| 7 | Demo packaging: Streamlit frontend, README, architecture diagram | ⚠️ Partial — frontend ✅, README ✅; diagram + demo scripts pending |

## 10. Known Issues (as of 2026-09-21)

1. **Dedup is effectively a no-op** — `deduplicate()` uses Jaccard@0.8 on 5-word shingles, but the math caps Jaccard for any chunk-vs-suffix pair below 0.8. Real fix: containment metric (`|A∩B| / min(|A|,|B|)`) with a length-ratio guard.
2. **Multi-query does not bridge domain vocabulary** — paraphrases preserve jargon ("PTO" → PTO-flavored variants). Documented limitation, not a bug. The LLM bridges residual gaps at generation time.
3. **Heading-only chunks are cited** — e.g. a 2-word "Employee Handbook" chunk. Minor; consider min-token filter at ingestion.
4. **Reranker top-1 can be the wrong chunk** when the query repeats an entity name (e.g. "SmartHome Hub"). LLM still cites correctly; top-1 highlight would be misleading.
5. **Cache is not thread-safe** — `core/cache.py` is an in-process LRU+TTL, not safe for `--workers > 1`. Swap for Redis before scaling.
6. **Duplicate DB rows** — some `failed` rows from earlier ingestion attempts coexist with `ready` rows. Clean before eval.
7. **Gemini free-tier quota is per project, not per key** — multiple keys in one project share one 20/day quota. Multi-key rotation only helps across separate projects.

## 11. Demo Scenarios (acceptance)

The finished demo must show:
- Direct factual Q&A with a clear supporting passage.
- Multi-document synthesis.
- Follow-up question that depends on the previous turn.
- Query benefiting from rewriting (jargon → corpus vocabulary).
- Query where hybrid retrieval or reranking changes the retrieved evidence.
- Table extraction from a multi-page PDF.
- Query with no supporting evidence → clean abstention.
- Side-by-side baseline vs. improved comparison using eval metrics.

## 12. Sign-Off Criteria

- [x] Document upload → processing → query, no manual DB work.
- [x] Grounded answers with traceable citations.
- [x] Semantic + keyword retrieval + reranking all demonstrated.
- [x] Follow-up questions handled; ≥1 difficult/ambiguous query pattern handled.
- [x] Assistant abstains on insufficient evidence.
- [x] Eval script runs repeatedly and produces measurable retrieval + generation metrics.
- [x] Complete demo starts from documented instructions on a clean environment.
- [x] Web UI for upload, chat, and feedback.
- [x] Pluggable LLM with fallback (Gemini → Ollama).
- [x] Versioned schema migrations (Alembic).
- [ ] Architecture diagram as a standalone artifact (currently ASCII in ARCHITECTURE.md).
- [ ] Demo scenario script automating the 7 PRD §11 scenarios.