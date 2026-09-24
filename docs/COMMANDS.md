# Git Bash Command Reference — Modern RAG Platform

Every command you need, in Git Bash syntax, with an inline comment explaining what each one does. This replaces the PowerShell version you had.

---

## 1. First-Time Setup

```bash
# Move into the project root. ALMOST every command below assumes you're here.
# In Git Bash, C:\Users\ADMIN becomes /c/Users/ADMIN (forward slashes, /c/ prefix).
cd /c/Users/ADMIN/Desktop/rag-platform

# Confirm you're in the right place — should print the path above.
pwd

# List everything in the current directory — sanity check before starting work.
ls -la

# Create your local .env from the template.
# Edit it afterward to set GEMINI_API_KEYS and POSTGRES_PASSWORD.
cp .env.example .env

# Verify the .env exists and has content.
cat .env

# Build the backend Docker image from backend/Dockerfile + requirements.txt.
# MUST be run after any change to backend source code — `up` alone does not
# rebuild, it just starts/recreates containers from the existing image.
docker compose build backend

# Same as above but ignores Docker's layer cache entirely.
# Use when a code change doesn't seem to take effect after a normal build.
# Slower (full reinstall) but guarantees nothing stale is reused.
docker compose build --no-cache backend

# Start all containers (Postgres + backend) detached (-d = background).
# Does NOT rebuild images — pair with `build` first if you changed code.
docker compose up -d

# Build (if needed) and start, combined.
docker compose up --build -d
```

---

## 2. Daily Docker Operations

```bash
# List all containers with their status. Look for "healthy" next to both
# rag_postgres and rag_backend before assuming the stack is ready.
docker compose ps

# Show the last 50 log lines from the backend container.
# First thing to check whenever something behaves unexpectedly.
docker compose logs backend --tail=50

# Follow backend logs live as new requests come in.
# Ctrl+C stops following (does NOT stop the container).
docker compose logs backend -f

# Stop and remove containers. Data volumes are PRESERVED.
# Safe to run anytime — DB data, uploads, and HF model cache survive.
docker compose down

# Stop and remove containers AND delete all data volumes.
# Wipes DB + uploaded files + HF model cache. Next start re-downloads models.
# Only use when you genuinely want a clean slate.
docker compose down -v

# Restart a single container without removing it (keeps volumes, keeps image).
# Does NOT pick up .env changes — use `up -d` for that.
docker compose restart backend

# Show container resource usage (CPU, memory) — useful for debugging slowness.
docker stats --no-stream
```

---

## 3. Running Commands Inside the Container

```bash
# Run any command inside the ALREADY-RUNNING backend container.
# Note: no `-it` needed for non-interactive commands.
docker compose exec backend <command>

# Confirm which Python classes actually exist inside the RUNNING container.
# Best command for catching "I edited the file but never rebuilt" mistakes.
docker compose exec backend grep -n "^class " /app/app/generation/providers.py

# Print a live config value from inside the container.
# Confirms a .env change actually took effect.
docker compose exec backend python -c "from app.config import settings; print(settings.enable_multi_query)"

# Quick syntax/import sanity check for one file — fails fast with a traceback
# if there's a Python error, before you waste time on a full query.
docker compose exec backend python -c "import app.generation.providers; print('imports fine')"

# Check what environment variables are actually set in the container.
docker compose exec backend printenv | grep -i "gemini\|ollama\|database"
```

---

## 4. Database Migrations (Alembic)

```bash
# Show which migration revision the DB currently thinks it's at.
# Expect "0002 (head)" after the multimodal upgrade.
docker compose exec backend alembic current

# Show migration history.
docker compose exec backend alembic history

# Mark an EXISTING database as already being at the latest revision,
# WITHOUT running any of the migration's SQL.
# Use this ONLY when introducing Alembic to a DB that already has tables.
docker compose exec backend alembic stamp head

# Execute all pending migrations. Use on a GENUINELY FRESH database only.
docker compose exec backend alembic upgrade head

# Generate a new migration by diffing models.py against the live DB.
# ALWAYS review the generated file before applying it.
docker compose exec backend alembic revision --autogenerate -m "description of change"
```

---

## 5. Backend Tests

```bash
# Tests need a real Postgres instance (pgvector has no faithful mock).
# Start just the DB, not the full stack.
docker compose up -d postgres

# Install Python deps LOCALLY (not in Docker) so pytest can import app code.
cd backend
pip install -r requirements.txt

# Run the full test suite with verbose per-test output.
# Expected: 23 passed.
pytest -v

# Run just one test file (faster iteration on a specific area).
pytest tests/test_phase4_advanced.py -v

# Run one specific test function.
pytest tests/test_phase4_advanced.py::test_deduplicate_removes_near_identical_chunks -v

# Run tests and stop at the first failure.
pytest -x

# Run tests matching a keyword.
pytest -k "table" -v

# Go back to repo root when done.
cd ..
```

---

## 6. Evaluation Harness

```bash
# Run the full evaluation: ingest sample corpus, run all golden questions
# through BOTH pipelines, save JSON + Markdown report to eval/results/.
# First run downloads models (~1.2 GB) and takes minutes.
python eval/run_eval.py

# Regenerate just the Markdown report from the most recent JSON results,
# without re-running ingestion or the pipelines.
python eval/regenerate_report.py

# Find the most recent eval report file (avoids typing the timestamp name).
ls -t eval/results/*.json | head -1

# View the most recent report contents.
cat $(ls -t eval/results/*.md | head -1)

# List all saved eval runs with sizes and timestamps.
ls -lath eval/results/
```

---

## 7. Frontend

```bash
# Install frontend's two dependencies (pure HTTP client — no DB or model libs).
pip install streamlit requests

# Launch the chat UI. Opens at http://localhost:8501.
# Backend must already be running (docker compose up -d).
streamlit run frontend/app.py

# Or, if you run the frontend in Docker (from repo root):
docker compose up -d frontend
```

---

## 8. API Testing with `curl`

**Git Bash handles `curl` properly** — unlike PowerShell, no quoting hell, no need for `-s` shenanigans. This is one of the few places Git Bash is objectively easier.

```bash
# --- Health check ---
curl http://localhost:8000/health
# Expected: {"status":"ok","app_env":"local","database":"ok"}

# --- Upload a document ---
# curl determines the file type from the extension and sends the right
# MIME type automatically. -F is "multipart form field".
curl -X POST "http://localhost:8000/documents" \
  -H "Authorization: Bearer change-me-dev-token" \
  -F "file=@/c/Users/ADMIN/Desktop/rag-platform/_scratch/handbook.docx" \
  -F 'metadata={"department":"hr"}'
# Expected: JSON with id, filename, status: "uploaded"
# Note the single quotes around the metadata JSON — double quotes
# would be eaten by the shell.

# --- Check a document's status (poll until "ready") ---
# Replace <id> with the document_id from the upload response.
curl "http://localhost:8000/documents/<id>" \
  -H "Authorization: Bearer change-me-dev-token"
# Expected: {"id":"...","status":"ready","failure_reason":null,...}

# --- List all documents ---
curl http://localhost:8000/documents \
  -H "Authorization: Bearer change-me-dev-token" \
  | python -m json.tool
# Pipe through `python -m json.tool` to pretty-print.
# Without the pipe, you get compact one-line JSON.

# --- Query: baseline pipeline ---
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}' \
  | python -m json.tool

# --- Query: improved pipeline with metadata filter ---
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved","filters":{"department":"hr"}}' \
  | python -m json.tool

# --- Query: with session_id for follow-ups ---
# Generate a session ID.
SESSION_ID=$(python -c "import uuid; print(uuid.uuid4())")
echo "Session: $SESSION_ID"

# Turn 1 — establishes history.
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What is the leave policy?\",\"pipeline\":\"improved\",\"session_id\":\"$SESSION_ID\"}" \
  | python -m json.tool
# Note: double-quoted JSON with escaped inner quotes so $SESSION_ID expands.

# Turn 2 — follow-up. Same session ID. Tests rewriting.
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What about sick leave?\",\"pipeline\":\"improved\",\"session_id\":\"$SESSION_ID\"}" \
  | python -m json.tool

# --- Submit feedback ---
curl -X POST "http://localhost:8000/feedback" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"query":"the question asked","answer":"the answer given","is_useful":true}' \
  | python -m json.tool

# --- See the error body (curl shows it by default; unlike Invoke-RestMethod) ---
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"","pipeline":"improved"}'
# Empty question triggers validation error; response body shows details.
```

---

## 9. Direct Database Queries (psql)

These run psql *inside* the Postgres container. All commands go through `docker compose exec postgres psql`.

```bash
# List all tables.
docker compose exec postgres psql -U postgres -d modern_rag -c "\dt"

# Describe the chunks table (columns, types, indexes).
docker compose exec postgres psql -U postgres -d modern_rag -c "\d chunks"

# Count documents by status.
docker compose exec postgres psql -U postgres -d modern_rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status;"

# Count chunks per modality (text / table / image) per document.
# -P pager=off disables the interactive pager so output prints directly.
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT d.filename, c.modality, COUNT(*)
FROM chunks c JOIN documents d ON d.id = c.document_id
GROUP BY d.filename, c.modality
ORDER BY d.filename, c.modality;
"

# Inspect one image chunk's content + metadata.
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT LEFT(content, 300), chunk_metadata->>'image_path'
FROM chunks
WHERE modality = 'image'
LIMIT 3;
"

# Search across all chunk content for a phrase.
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT d.filename, LEFT(c.content, 100)
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.content ILIKE '%Web Access Symbol%';
"

# Delete a specific document (cascade deletes its chunks).
docker compose exec postgres psql -U postgres -d modern_rag -c "DELETE FROM documents WHERE filename = 'sample3.docx';"

# Note: enum values are UPPERCASE in the DB even though Python defines them
# lowercase. Use 'FAILED', not 'failed', in raw SQL.
docker compose exec postgres psql -U postgres -d modern_rag -c "DELETE FROM documents WHERE status='FAILED';"
```

---

## 10. Debugging Diagnostics (direct pipeline introspection)

Bypass the API entirely — call internal functions inside the container to isolate which stage is responsible for an unexpected result.

```bash
# Raw vector similarity for a query, ignoring hybrid/rerank.
docker compose exec backend python -c "
from app.embeddings.provider import get_embedding_provider
from app.retrieval.vector_store import vector_search
from app.db.session import SessionLocal
db = SessionLocal()
embedding = get_embedding_provider().embed_query('your question here')
for r in vector_search(db, embedding, top_k=3):
    print(round(r.score, 4), '|', r.filename, '|', r.content[:60])
"

# Hybrid scores AND reranker scores side by side.
docker compose exec backend python -c "
from app.embeddings.provider import get_embedding_provider
from app.retrieval.hybrid import hybrid_search
from app.retrieval.reranker import rerank
from app.db.session import SessionLocal
db = SessionLocal()
q = 'your question here'
embedding = get_embedding_provider().embed_query(q)
candidates = hybrid_search(db, q, embedding, top_k=10)
print('--- hybrid ---')
for c in candidates: print(round(c.score, 4), '|', c.filename)
print('--- reranked ---')
for c in rerank(q, candidates, top_n=4): print(round(c.score, 4), '|', c.filename)
"

# See exactly what multi-query expansion generates for a question.
docker compose exec backend python -c "
from app.generation.providers import get_llm_client
from app.retrieval.query_transform import expand_queries
print(expand_queries(get_llm_client(), 'your question here'))
"

# Test the Gemini-to-Ollama fallback chain works.
# Temporarily set GEMINI_API_KEYS to invalid values in .env, then:
docker compose up -d backend
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}'
# Should still succeed (via Ollama).
docker compose logs backend --tail=20
# Should show "primary_llm_failed_falling_back_to_ollama" warnings.
# Restore your real key(s) and `docker compose up -d backend` again.
```

---

## 11. Timing / Latency Checks

```bash
# Measure a query's wall time in seconds.
time curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}' \
  > /dev/null
# `time` is a bash builtin — measures the whole curl call.
# `>/dev/null` discards the response body so you only see timing.

# Measure a stateless query with `improved` pipeline.
time curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved"}' \
  > /dev/null

# Check p50/p95 latency from the logs (if you log duration_ms).
docker compose logs backend --tail=200 | grep "query_answered" | tail -20
```

---

## 12. Log Analysis

```bash
# Show the last 50 lines of backend logs.
docker compose logs backend --tail=50

# Search for specific error patterns.
docker compose logs backend --tail=500 | grep -i "error\|exception\|traceback"

# Find all rate-limit or retry events.
docker compose logs backend --tail=500 | grep -E "429|rate_limit|retry|RESOURCE_EXHAUSTED"

# Check whether the modality boost fired for a query.
docker compose logs backend --tail=200 | grep "image_boost"

# Show stage-timing events (per-stage tracing).
docker compose logs backend --tail=500 | grep '"stage":"\(retrieve\|rerank\|generate\|compress\)"'

# Watch logs live and filter to a specific pattern.
docker compose logs -f backend | grep --line-buffered "query_answered"

# Save logs to a file for later analysis.
docker compose logs backend > backend-logs-$(date +%Y%m%d-%H%M%S).txt
```

---

## 13. Git Operations (as used in this project)

```bash
# Check current branch and see modified/untracked files.
git status

# Show recent commit history (one-line format, with branch decorations).
git log --oneline -10

# Stage specific files (preferred over `git add .` — less accidental).
git add backend/app/ingestion/parsers.py backend/app/ingestion/pipeline.py

# Stage everything not gitignored.
git add .

# ⚠️ CRITICAL: review what's staged BEFORE committing.
# Verify .env is NOT in the list.
git status

# Commit with a descriptive message.
git commit -m "Phase 4: multimodal ingestion — text + tables + images"

# Push to GitHub.
git push

# Create a tag (like the safety net tag used before big changes).
git tag text-only-baseline
git push origin text-only-baseline

# Restore a single file from an earlier commit or tag.
git checkout text-only-baseline -- backend/app/ingestion/parsers.py

# Check that a sensitive file is actually gitignored.
git check-ignore .env
# Should output: .env
# If it outputs nothing, .env is NOT ignored — stop and fix .gitignore.
```

---

## 14. Environment Variable Inspection

```bash
# Show what .env contains (careful: contains secrets).
cat .env

# Show only non-secret variable names (values hidden).
grep -E "^[A-Z]" .env | cut -d= -f1

# Confirm a specific variable from inside the backend container.
docker compose exec backend printenv LLM_PROVIDER
docker compose exec backend printenv OLLAMA_VISION_MODEL
docker compose exec backend printenv HF_HUB_OFFLINE

# Check all backend env vars that start with a prefix.
docker compose exec backend printenv | grep "LLM\|OLLAMA\|GEMINI"
```

---

## 15. Ollama Commands (host-side, not in container)

```bash
# List models downloaded locally.
curl -s http://localhost:11434/api/tags | python -m json.tool

# Or if the ollama CLI is on PATH:
ollama list

# Pull a model.
ollama pull moondream:1.8b
ollama pull qwen2.5:7b

# Remove a model to free disk space.
ollama rm llama3.2:3b

# Check if Ollama is running.
curl -s http://localhost:11434/api/tags > /dev/null && echo "Ollama up" || echo "Ollama down"

# Test Ollama reachability from INSIDE the container.
docker compose exec backend curl -s http://host.docker.internal:11434/api/tags
# If this fails but the host-side curl works, add to docker-compose.yml
# under the backend service:
#     extra_hosts:
#       - "host.docker.internal:host-gateway"
```

---

## 16. Cleanup

```bash
# Remove dangling Docker images (unreferenced layers).
docker image prune -f

# Remove stopped containers.
docker container prune -f

# Show Docker disk usage.
docker system df

# Full cleanup — remove everything not in use.
# ⚠️ This will remove the postgres volume if containers are stopped.
docker system prune -a

# Delete Python cache directories (safe, regenerated next run).
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
```

---

## Quick Reference: Command → Purpose

| Command | Purpose |
|---|---|
| `cd /c/Users/ADMIN/Desktop/rag-platform` | Move to repo root (bash-style path) |
| `docker compose build backend` | Rebuild image after code changes |
| `docker compose up -d` | Start containers, pick up .env changes |
| `docker compose down` | Stop containers, keep data |
| `docker compose down -v` | Stop containers, wipe all data |
| `docker compose logs backend -f` | Live log tail |
| `docker compose exec backend <cmd>` | Run something inside the container |
| `docker compose exec backend alembic current` | Check DB migration state |
| `docker compose exec postgres psql -U postgres -d modern_rag -c "<sql>"` | Query the DB |
| `cd backend && pytest -v` | Run backend tests |
| `python eval/run_eval.py` | Run full evaluation |
| `streamlit run frontend/app.py` | Launch the chat UI |
| `curl -X POST http://localhost:8000/query ... \| python -m json.tool` | Call the API, pretty-print JSON |
| `time curl ...` | Measure query wall time |
| `docker compose logs backend --tail=200 \| grep "pattern"` | Search logs |
| `git check-ignore .env` | Verify .env is excluded from git |
| `git checkout <tag> -- <file>` | Restore a single file from a tag |
| `ollama list` | Show downloaded Ollama models |
| `find . -type d -name __pycache__ -exec rm -rf {} +` | Delete Python caches |

---

## Key Differences from PowerShell

Three things that trip people up switching from PowerShell to Git Bash:

**1. Paths use forward slashes and `/c/` prefix.**
- PowerShell: `C:\Users\ADMIN\Desktop\rag-platform`
- Git Bash: `/c/Users/ADMIN/Desktop/rag-platform`

**2. Line continuations differ.**
- PowerShell uses backtick `` ` ``
- Git Bash uses backslash `\`

```bash
# Git Bash line continuation
curl -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"..."}'
```

**3. JSON quoting is EASIER in Git Bash.** Single quotes preserve everything:

```bash
# Git Bash — single quotes just work
curl ... -d '{"question":"What is the leave policy?","pipeline":"improved"}'

# If you need a shell variable inside, use double quotes with escapes
curl ... -d "{\"question\":\"$QUESTION\",\"pipeline\":\"improved\"}"
```

In PowerShell, embedded JSON caused the whole "curl.exe mangles quotes" saga. Git Bash sidesteps that entirely.

---

## The three commands you'll run most often

```bash
# 1. Start the stack and confirm it's healthy
docker compose up -d && docker compose ps

# 2. Ask a question, pretty-printed
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved"}' \
  | python -m json.tool

# 3. Check what the pipeline did
docker compose logs backend --tail=30 | grep -E "stage|retrieval_results|llm_usage"
```