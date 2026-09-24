```markdown
# Modern RAG Platform

An internal knowledge assistant: upload documents (PDF/DOCX/TXT/MD), ask
natural-language questions, get answers grounded in those documents with
traceable citations — and clean abstention when the corpus doesn't contain
the answer.

Demonstrates the full modern-RAG stack (structure-aware chunking, hybrid
retrieval, cross-encoder reranking, query transformation, contextual
compression, evaluation, observability) and ships **two pipelines that can
be A/B compared on the same evaluation set**.

> **Companion docs:** [`HLD.md`](HLD.md) (architecture, decisions, phase status),
> [`LLD.md`](LLD.md) (module detail, schemas, API contracts),
> [`docs/MEMORY.md`](docs/MEMORY.md) (session notes, known gotchas).

---

## Quick start

```bash
git clone <repo> && cd rag-platform
cp .env.example .env
# Edit .env — set GEMINI_API_KEYS (see "Configuration" below)

docker compose up --build
```

Then:

- **Frontend:** http://localhost:8501
- **API docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

First startup downloads two local models (`bge-small-en-v1.5` embeddings,
`bge-reranker-base` reranker) into a persistent `hf_cache` Docker volume —
~500 MB, once, requires internet the first time only.

---

## Prerequisites

- **Docker Desktop** (Windows/macOS) or Docker Engine + Compose v2 (Linux)
- **Python 3.11+** (only needed for host-side scripts like the eval harness)
- **Ollama** (optional but recommended as fallback) — see `docs/MEMORY.md`

---

## Configuration

All configuration lives in `.env` at the repo root. `app/config.py` is the
**only** module that reads environment variables — no other file touches
`os.environ`, which is what makes "secrets never hard-coded" auditable.

### Essential settings

```env
# Database — host-side tools use this; the backend container overrides host to `postgres`
DATABASE_URL=postgresql+psycopg://postgres:<password>@localhost:5433/modern_rag

# Embeddings — local, no API key, runs offline
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384

# LLM — Gemini primary, Ollama fallback
LLM_PROVIDER=gemini_with_ollama_fallback
GEMINI_API_KEYS=key1,key2,key3
GEMINI_MODEL=gemini-2.5-flash
OLLAMA_MODEL=qwen3:8b
OLLAMA_HOST=http://host.docker.internal:11434

# Retrieval
RETRIEVAL_TOP_K=8
HYBRID_ALPHA=0.5
RERANK_ENABLED=true
RERANK_TOP_N=4
ENABLE_MULTI_QUERY=false
CONTEXT_TOKEN_BUDGET=2000

# Auth
API_AUTH_TOKEN=change-me-dev-token
```

### Gemini keys — the caveat that matters

Google's free-tier rate limit is **per Google Cloud project**, not per API
key. Creating three keys inside one project gives you 20 requests/day
total, not 60. To get 60/day, each key must come from a **separate
project**.

To create separate-project keys:

1. Go to https://aistudio.google.com/apikey
2. Click "Create API key" → choose **"in new project"** (not "in existing")
3. Repeat twice more, each in a new project
4. Paste all three keys, comma-separated, into `GEMINI_API_KEYS`

If you don't have a Gemini key or hit quota, the Ollama fallback keeps the
system running. `LLM_PROVIDER=ollama` uses the local model exclusively.

---

## Usage

### Web UI

`http://localhost:8501` — four tabs:

- **Chat** — ask questions, see answers with expandable citations, 👍/👎 feedback
- **Upload** — drop a file, watch ingestion progress, query when ready
- **Documents** — everything in the knowledge base, with status
- **Settings** — switch pipeline (baseline vs. improved), set the API token

### API

All routes require `Authorization: Bearer <API_AUTH_TOKEN>`.

```bash
# Upload
curl -X POST http://localhost:8000/documents \
  -H "Authorization: Bearer change-me-dev-token" \
  -F "file=@myfile.pdf" \
  -F 'metadata={"department":"hr"}'

# Query
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved"}'

# Feedback
curl -X POST http://localhost:8000/feedback \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"query":"...","answer":"...","is_useful":true}'

# List documents
curl http://localhost:8000/documents \
  -H "Authorization: Bearer change-me-dev-token"
```

Full OpenAPI: `http://localhost:8000/docs`.

### Two pipelines

The `pipeline` parameter selects which orchestrator runs:

- **`baseline`** — vector search → threshold → LLM. Simple, fast (~65 ms).
- **`improved`** — query rewrite → multi-query expansion → hybrid retrieval
  → rerank → compression → LLM. Slower (~1050 ms), higher quality.

Phase 5 eval numbers (baseline → improved): hit_rate 0.50 → 0.83,
MRR 0.50 → 0.83, keyword_coverage 0.50 → 0.75, abstention_accuracy
0.57 → 0.86.

---

## Architecture

```
Frontend (Streamlit)  →  Backend (FastAPI)
                            │
                ┌───────────┼─────────────┐
                ▼           ▼             ▼
          Postgres     Embedding       LLM provider
          + pgvector   (local, no      (Gemini primary,
          (metadata,   API key)         Ollama fallback)
          vectors,
          full-text,
          history)
```

Ingestion runs as a FastAPI `BackgroundTask`; the client polls
`GET /documents/{id}` until `ready` or `failed`.

Query path (improved):
`rewrite → multi-query → hybrid (vector + keyword) → rerank → compress → LLM → answer + citations`.

See `HLD.md` for the full picture and `docs/ARCHITECTURE.md` for module
detail.

---

## Evaluation

```bash
# Runs the golden dataset through both pipelines, writes a report
python eval/run_eval.py

# Or with the real LLM for answer-quality scoring
python eval/run_eval.py --real-llm
```

Output: `eval/results/report_<timestamp>.json` + `.md`.

The harness scopes queries to a bundled sample corpus (`eval/sample_corpus/`)
via `document_ids`, so user uploads in the same DB never contaminate the
benchmark.

---

## Database migrations

Schema changes go through Alembic:

```bash
# After editing a model in backend/app/db/models.py:
docker compose exec backend alembic revision --autogenerate -m "add column X"
# Review the generated file in backend/alembic/versions/
docker compose exec backend alembic upgrade head
```

The existing schema is stamped at revision `0001`. On a fresh database,
`alembic upgrade head` builds it from scratch.

---

## Testing

```bash
# From repo root, with Postgres running:
docker compose up -d postgres

cd backend && pip install -r requirements.txt
pytest -v
```

Unit tests cover chunking, hybrid fusion, metadata filter construction,
and compression. Integration tests cover upload → ingest → query.

---

## Troubleshooting

### Port 5432 conflict (Windows)

If a native Windows Postgres is running, it collides with the Docker
container. The compose file maps Postgres to **5433** on the host. If
`pytest` fails with `password authentication failed` or
`type "vector" does not exist`, you're hitting the native instance:

```powershell
netstat -ano | findstr :5432
Get-Process -Id <PID>
```

Fix: either stop the native Postgres, or confirm `.env`'s `DATABASE_URL`
uses `localhost:5433`.

### `Cannot copy out of meta tensor; no data!`

Model download was interrupted (VPN, firewall, flaky connection). The
`device="cpu"` + `low_cpu_mem_usage=False` kwargs in
`embeddings/local.py` and `retrieval/reranker.py` force the safe load
path — do not remove them.

Fix: delete the model cache and rebuild:

```bash
docker compose down -v
docker compose up --build
```

### Every query falls back to Ollama

Gemini free tier is exhausted (20 req/day/project) or blocked by network.
Check:

```bash
docker compose logs backend --tail 100 | grep 429
```

Options: create a new key in a separate project, or set
`LLM_PROVIDER=ollama` for a predictable local experience.

### Slow queries (10s+)

Free-tier Gemini 503s trigger SDK retries with exponential backoff. To
reduce latency:

1. Confirm `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are in
   `docker-compose.yml` under the backend service
2. Try `GEMINI_MODEL=gemini-2.5-flash-lite` for lower load
3. Set `LLM_PROVIDER=ollama` with a smaller model (`llama3.2:3b`)

### Frontend shows "Backend unreachable"

The frontend reaches the backend via Docker's service name. Verify:

```bash
docker compose exec frontend python -c "import requests; print(requests.get('http://backend:8000/health', timeout=5).json())"
```

If that fails, both services may be on different networks — check
`docker-compose.yml` has both under the same `services:` block without
custom network config.

---

## Repository layout

```
rag-platform/
├── backend/              FastAPI app + ingestion + retrieval + generation
├── frontend/             Streamlit UI
├── eval/                 Golden dataset + harness + results
├── docs/                 PRD, ARCHITECTURE, RULES, DESIGN, TASKS, MEMORY
├── docker-compose.yml
├── .env.example
├── HLD.md                High-level design
├── LLD.md                Low-level design
└── README.md             This file
```

---

## Known limitations

- **Auth is one shared bearer token** — no per-user access control. Every
  document is visible to anyone with the token. First thing to replace
  for real multi-user use.
- **Dedup in compression is currently near-no-op** — Jaccard@0.8 cannot
  match overlapping-window near-duplicates. Fix: containment metric.
- **Multi-query preserves jargon** rather than bridging to corpus
  vocabulary ("PTO" → PTO-flavored variants, not "paid annual leave").
  The LLM bridges the gap at generation time.
- **Reranker top-1 can be the wrong chunk** when the query repeats a
  document's title; the LLM cites correctly anyway.
- **No frontend beyond Streamlit** — spec asked for "a simple web UI";
  this satisfies it.

See `HLD.md` §9 for the full list.

---

## License

Demo project. Sample files in `eval/sample_corpus/` are from
[Sample-Files.com](https://sample-files.com), free for testing use.
```


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