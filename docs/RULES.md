## `docs/RULES.md`

Save at `docs/RULES.md`.

```markdown
# Rules for Contributors and AI Agents

**This file is binding.** Violating these rules is a bug, even if tests pass.
Everything below exists because breaking it caused a real, non-obvious
failure at some point in this project's development.

**Companion docs:** `ARCHITECTURE.md`, `DESIGN.md`, `../HLD.md`, `../LLD.md`, `MEMORY.md`.

---

## 1. Architectural Invariants

### 1.1 `app/config.py` is the only module that reads `os.environ`
No other file may import `os`, call `os.getenv`, or read `os.environ`
directly. All settings come through `settings` in `app/config.py`. This is
what makes "secrets never hard-coded" auditable rather than aspirational.

### 1.2 The `LLMClient` interface does not change
`LLMClient.generate(system: str, user: str) -> str`. Both orchestrators
call it, in two places each (query rewriting + final answer). Any change
to the signature, return type, or failure semantics breaks four call sites
silently.

If you need new behavior — streaming, token counts, temperature control —
wrap it. Do not extend the interface.

### 1.3 Orchestrators do not talk to the database directly
They call retrieval, reranking, compression, and generation through their
package interfaces. No raw SQL in `orchestrator/`. No `db.execute()`
outside `db/` and `retrieval/`.

### 1.4 Embeddings are local. Do not "upgrade" them casually.
`BAAI/bge-small-en-v1.5`, 384 dimensions. `EMBEDDING_DIM` is baked into
the `vector(384)` column type in the database. Changing the model without
updating `EMBEDDING_DIM` and **re-ingesting every document** corrupts the
index.

If you switch embedding models, that is a **migration**, not a config edit.
Plan it: stop the backend, truncate `chunks`, deploy the new model, restart,
re-run the eval, verify numbers didn't regress.

### 1.5 Retrieval never writes to the database
`retrieval/` is read-only against `chunks` and `documents`. Writes only
happen in `ingestion/`, `conversation/`, and `api/feedback.py`.

### 1.6 Two orchestrators stay separate
`naive_rag.py` and `improved_rag.py` are two real implementations, not one
with a flag. The whole point is that a comparison between them is
meaningful. Do not merge them.

---

## 2. Landmines — Do Not "Clean Up"

### 2.1 `device="cpu"` + `low_cpu_mem_usage=False` in model loading
Present in `embeddings/local.py::_load_model` and
`retrieval/reranker.py::_load_reranker`. **Do not remove these kwargs to
make the code look tidier.**

Without them, newer `transformers`/`accelerate` versions load weights via
a "meta device" placeholder that is only materialized if the download
completes cleanly. Any network hiccup (VPN, corporate firewall, flaky
Wi-Fi) leaves the model half-loaded and throws:

```
NotImplementedError: Cannot copy out of meta tensor; no data!
```

on first use, with a stack trace that gives **no hint** it is a download
problem. This bug cost a full day to diagnose. The kwargs force the
slow-but-bulletproof load path.

### 2.2 The `hf_cache` volume in `docker-compose.yml`
Mounted to `/root/.cache/huggingface` in the backend service so the
embedding and reranker models download **once**, not on every container
recreate. Removing this volume dramatically increases the odds of hitting
the meta-tensor bug. Leave it.

### 2.3 The hybrid fused score is NOT an abstention gate
`hybrid.py` min-max normalizes per query. That guarantees the top
candidate is near 1.0 regardless of whether it is genuinely relevant —
normalization is relative to the batch, not absolute. Confirmed
empirically: "What is the capital of France?" cleared a naive 0.2
threshold on this corpus and returned a citation.

**Do not use the fused score to decide whether to answer.** Abstention
gates on raw cosine.

### 2.4 The reranker score is NOT an abstention gate either
`BAAI/bge-reranker-base` output is not a calibrated 0–1 scale. It
correctly ranked a vocabulary-mismatched query's best chunk at #1 with
score **0.0056**. Applying a `>= 0.15` filter to this silently vetoed
genuine matches. The filter was removed.

**Rerank reorders only.** Abstention is gated upstream.

### 2.5 Abstention gates on raw cosine of the resolved question
`RAW_VECTOR_MIN_RELEVANCE_SCORE = 0.6` (in `improved_rag.py`) and
`MIN_RELEVANCE_SCORE = 0.6` (in `naive_rag.py`). Identical on purpose —
both pipelines share the same embedding model.

Empirically calibrated against 3 data points (0.84 relevant; 0.50 and
0.38 irrelevant). **Not a universal constant. Revisit once the Phase 5
eval set provides enough true-positive/true-negative pairs.** Do not
lower it to "make a failing query pass" — that regresses abstention on
off-corpus questions.

### 2.6 Query rewriting must permit "return unchanged"
`query_transform.py`'s `REWRITE_SYSTEM_PROMPT` includes explicit rules:
- If the new question is already standalone, return it **UNCHANGED**.
- Do NOT append context from earlier turns just because it appeared earlier.

This was added after a real bug: after a turn about the SmartHome Hub
document, a new standalone question ("What was the PDF market share in
2020 according to the table?") was rewritten to *"...in the SmartHome Hub
document?"* — injecting a topic that was never mentioned, pointing
retrieval at the wrong document, and causing a false abstention.

If you touch this prompt, keep the "unchanged" rule and at least one
counter-example. The LLM's default bias is to include history whenever
it's present.

### 2.7 The improved pipeline's relevance gate considers the ORIGINAL question
If the query was rewritten, `improved_rag.py` computes raw vector
relevance for **both** the resolved query and the original, and takes the
max. This is the safety net for imperfect rewrites — even if the LLM
corrupts the query, retrieval still sees the user's actual words.

Do not remove this fallback. It is not redundant with §2.6; the two fixes
together are belt-and-suspenders.

---

## 3. Coding Standards

### 3.1 Type hints everywhere
Public functions have fully-annotated signatures. `list[RetrievedChunk]`,
not `list`. `UUID | None`, not `Optional[UUID]` (Python 3.11+, PEP 604
union syntax).

### 3.2 Structured logging, never f-strings in logs
```python
# YES
logger.info("rerank_complete", extra={"n_in": len(chunks), "n_out": len(reranked)})

# NO
logger.info(f"Reranked {len(chunks)} chunks down to {len(reranked)}")
```

The JSON formatter in `observability/logging.py` merges `extra=` fields
into the log line as structured data. f-strings become unqueryable text.

### 3.3 Never log secrets or content
Convention (not enforced by code): `extra=` never contains file contents,
request bodies, API keys, or bearer tokens. This is a hard rule for
anything labelled `# SECURITY`.

### 3.4 Exceptions are domain types
Raise `RagPlatformError` subclasses from `core/exceptions.py`. `main.py`
has a single handler that converts any subclass to a clean 400 JSON body.
Do not raise bare `Exception`. Do not leak stack traces to the client.

### 3.5 Fail gracefully, mark the document
Any error in `ingestion/pipeline.py` must set `documents.status = FAILED`
with a `failure_reason`, and must not raise past the background-task
boundary. If you add a new ingestion stage, wrap it.

### 3.6 One module, one concern
`retrieval/compression.py` does deduplication and budget selection.
`retrieval/reranker.py` does reranking. Do not merge them "because they
are both small". They are separately testable and separately swappable.

### 3.7 Enum values are uppercase in Postgres
`DocumentStatus` enum is defined lowercase in Python
(`DocumentStatus.READY`) but stored **uppercase** in Postgres (`READY`).
Any raw SQL must use uppercase labels:

```sql
-- YES
DELETE FROM documents WHERE status='FAILED';

-- NO — "invalid input value for enum document_status: failed"
DELETE FROM documents WHERE status='failed';
```

### 3.8 Frontend is an HTTP client only
`frontend/app.py` never imports from `app.*`. It talks to the backend over
HTTP exclusively. This keeps the frontend replaceable (React, plain HTML)
without touching backend code.

---

## 4. Testing Requirements

### 4.1 What must have a test
- Any pure function in `ingestion/`, `retrieval/`, or `orchestrator/`.
- Any new API route (at least: happy path + one validation failure).
- Any new config value (at least: default + one override).

### 4.2 What must NOT need a database
If a test claims to cover a pure function, it must be importable and
testable **without** a Postgres connection. If your test file pulls in
`app.db.session` at import time, the import chain is wrong — fix the
imports, not the test infrastructure.

### 4.3 No tests against live models
Reranker, LLM, and embedding tests use fakes or skip. Real-model
verification is manual, against a running Docker deployment.

### 4.4 Coverage honesty
The coverage map in `../LLD.md` §8 must accurately reflect what passes.
If a test starts failing, fix the test or fix the map — do not let them
diverge.

---

## 5. API Contract Rules

### 5.1 Never break existing fields
Add fields; do not rename or remove them. The eval harness depends on
`abstained`, `citations`, and `resolved_query`.

### 5.2 Pipeline enum is `baseline | improved`
Not `naive`. The module is `naive_rag.py`; the enum value is `baseline`.
Do not add aliases — they invite drift.

### 5.3 Ingestion is async
`POST /documents` returns 201 with `status: UPLOADED`. Ingestion runs in
a `BackgroundTask`. Clients must poll `GET /documents/{id}` until `READY`
or `FAILED`. Do not change this to synchronous — it would block the API
on multi-megabyte files.

### 5.4 Caching is bypassed when `session_id` is present
Conversation state can change the resolved query between calls, so
session-scoped queries must never be cached. `core/cache.py` enforces
this by keying only on `(pipeline, question, document_ids, filters)`.

### 5.5 The `abstained` flag reflects the LLM, not just retrieval
`abstained=True` is set when:
1. Retrieval found no candidates (upstream check)
2. Raw relevance was below threshold (upstream check)
3. The LLM echoed `ABSTENTION_MESSAGE` in its output (post-generation check)

All three are legitimate refusals. A UI or metric treating `abstained` as
ground truth must see all three. Do not "simplify" by removing any.

---

## 6. Git & Commit Rules

### 6.1 Commit messages: `<scope>: <imperative>`
```
retrieval: fix dedup to use containment instead of Jaccard
generation: add Gemini multi-key rotation with Ollama fallback
ingestion: reject heading-only chunks below 20 tokens
docs: correct LLD §4 rerank filter description
```

### 6.2 Never commit `.env`
Only `.env.example`. If you accidentally commit a real key, **rotate it
immediately** — do not just delete the commit. Public Git history is
forever.

### 6.3 Don't commit model caches or uploads
`hf_cache`, `upload_data`, and `data/` are Docker volumes, not in the repo.
Do not add `.cache/`, `models/`, or `data/` to git.

### 6.4 Don't commit eval results unless asked
`eval/results/` is gitignored by default. Commit a specific report only
when it's the artifact you want to preserve.

---

## 7. Prohibitions

Do **not**:
- Add LangChain, LlamaIndex, Haystack, or similar frameworks.
- Replace Postgres + pgvector with a dedicated vector DB without updating
  `ARCHITECTURE.md` and getting sign-off.
- Change the embedding model without a re-ingestion plan.
- Change `LLMClient`'s interface.
- Apply a score threshold to the reranker output.
- Use hybrid's fused score as an abstention gate.
- Lower `RAW_VECTOR_MIN_RELEVANCE_SCORE` to make a failing query pass.
- Remove the "return unchanged" rule from the rewrite prompt.
- Read `os.environ` outside `app/config.py`.
- Query `documents.status` with lowercase strings in raw SQL.
- Import `app.*` from `frontend/app.py`.
- Refactor unrelated code "while you're in there". Open a separate change.
- Add `--no-cache` to the Docker build "to be safe". It is 10× slower and
  almost never necessary.

---

## 8. When You Are Unsure

1. Check `MEMORY.md` — most gotchas are already documented there.
2. Check `../HLD.md` §5 — most design choices have a stated rationale.
3. Check `../LLD.md` — most algorithms have a written explanation.
4. Check the actual code before proposing a rebuild. This project has
   had a working implementation replaced by a "cleaner" one only to
   discover the original was correct and the rebuild was unnecessary.
   That cost a full session. Read first.
5. If the answer is still unclear, **ask** rather than guess. Documented
   wrong assumptions cost more than a clarifying question.
```