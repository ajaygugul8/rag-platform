Here's the complete `docs/COMMANDS.md`. Save it at `docs/COMMANDS.md`.

```markdown
# Commands Reference - Modern RAG Platform

Every command used to set up, run, test, debug, and evaluate this
project. Organized by task. Each command has a one-line explanation of
what it does and why you'd run it.

**Shell note:** This project was developed on Windows. Most commands
below are written for **Git Bash** (the shell that works best for this
project on Windows). Where PowerShell differs, the difference is noted.

**Path note:** Git Bash uses `/c/Users/ADMIN/...` for Windows paths.
PowerShell uses `C:\Users\ADMIN\...`. WSL uses `/mnt/c/Users/ADMIN/...`.

---

## 1. Opening the Right Shell

Before running anything, you need to be in the right shell, in the right
directory.

### Launch Git Bash from PowerShell

```powershell
& "C:\Program Files\Git\git-bash.exe" --cd="C:\Users\ADMIN\Desktop\rag-platform"
```

Opens a new Git Bash window already in the project directory. Use this
when you're in PowerShell and want to switch to Git Bash.

### Confirm you're in the right shell and directory

```bash
pwd
```

Expected: `/c/Users/ADMIN/Desktop/rag-platform`

If it's not, `cd` to it:

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
```

### Which shell am I in?

- **Git Bash:** prompt contains `MINGW64`, paths use `/c/`
- **PowerShell:** prompt starts with `PS`, paths use `C:\`
- **WSL:** prompt is `user@host:/mnt/c/...`, git doesn't work across filesystem boundary by default

---

## 2. First-Time Setup

### Copy the env template

```bash
cp .env.example .env
```

Creates your local `.env` from the template. Then edit it and set at
least `GEMINI_API_KEYS` (comma-separated, no spaces) and
`POSTGRES_PASSWORD`.

### Verify `.env` contents

```bash
cat .env
```

Shows the file. Useful to confirm your changes took effect and to spot
formatting mistakes.

### Build the backend Docker image

```bash
docker compose build backend
```

Builds the backend image from `backend/Dockerfile` and
`backend/requirements.txt`. **Must be run after any change to backend
source code.** `docker compose up` alone does NOT rebuild — it just
starts containers from whatever image already exists.

First build downloads PyTorch, Docling, sentence-transformers (~2 GB)
and takes 5–10 minutes.

### Build ignoring cache

```bash
docker compose build --no-cache backend
```

Slower full reinstall. Use when a code change doesn't seem to take effect
after a normal build.

### Start everything

```bash
docker compose up -d
```

Starts Postgres + backend + frontend in the background (`-d` = detached).
Also picks up `.env` changes (unlike `restart`).

### Build + start combined

```bash
docker compose up --build -d
```

One command that builds only if needed and starts. Convenient for
day-to-day work.

---

## 3. Daily Operations

### Check what's running

```bash
docker compose ps
```

Lists all containers and their status. Look for `healthy` next to both
`rag_postgres` and `rag_backend`.

### Show last 50 log lines

```bash
docker compose logs backend --tail=50
```

First thing to check whenever something behaves unexpectedly. Also
useful: `--tail=200` or `--tail=500` for more history.

### Follow logs live

```bash
docker compose logs backend -f
```

Streams new log lines as they arrive. `Ctrl+C` stops following without
stopping the container.

### Filter logs by pattern

```bash
docker compose logs backend --tail=200 | grep "query_answered"
docker compose logs backend --tail=200 | grep -E "429|rate_limit|retry"
docker compose logs backend --tail=200 | grep "image_boost"
docker compose logs backend --tail=200 | grep "stage_completed"
```

Grep is your best tool for finding specific events in JSON log output.
Common patterns to search for: `error`, `exception`, `429`, `retry`,
`stage_started`, `stage_completed`, `llm_usage`, `retrieval_results`,
`image_boost`, `primary_llm_failed_falling_back_to_ollama`.

### Restart a single service

```bash
docker compose restart backend
```

Restarts the process without removing the container. Does NOT pick up
`.env` changes — use `docker compose up -d` for that.

### Stop everything

```bash
docker compose down
```

Stops and removes containers. **Data volumes are preserved** — Postgres
data, uploaded files, and model cache all survive. Safe to run anytime.

### Stop and wipe all data

```bash
docker compose down -v
```

**Wipes the Postgres volume AND the model cache.** Next start
re-downloads all models (~2 GB). Only use when you genuinely want a
clean slate, e.g. to fix schema drift on a disposable dev database.

### Container resource usage

```bash
docker stats --no-stream
```

Shows CPU and memory per container. Useful for debugging slowness or
confirming a service isn't resource-starved.

---

## 4. Running Commands Inside the Container

### General pattern

```bash
docker compose exec backend <command>
```

Runs any command inside the already-running backend container. This is
the canonical way to verify code state, run tests, apply migrations, or
inspect internals.

### Confirm which code is actually running

```bash
docker compose exec backend grep -n "^class " /app/app/generation/providers.py
```

Shows which Python classes exist inside the running container right now.
**Best command for catching "I edited the file but the container never
got rebuilt" mistakes.**

### Print a config value from inside the container

```bash
docker compose exec backend python -c "from app.config import settings; print(settings.enable_multi_query)"
docker compose exec backend python -c "from app.config import settings; print(settings.llm_provider)"
docker compose exec backend python -c "from app.config import settings; print(settings.ollama_vision_model)"
```

Confirms an `.env` change actually took effect. Faster than inspecting
logs.

### Syntax check without running

```bash
docker compose exec backend python -c "import app.generation.providers; print('imports fine')"
docker compose exec backend python -c "from app.orchestrator import improved_rag; print('ok')"
```

Fails fast with a traceback if there's a Python error. Run this before
running a full query test — saves time when you've just edited a file.

### Print environment variables

```bash
docker compose exec backend printenv | grep -E "GEMINI|OLLAMA|HF_"
docker compose exec backend printenv HF_HUB_OFFLINE
docker compose exec backend printenv LLM_PROVIDER
docker compose exec backend printenv OLLAMA_VISION_MODEL
```

Shows actual env vars from inside the container. Confirms `.env` values
made it through Docker Compose.

---

## 5. Database Migrations (Alembic)

### Check current migration state

```bash
docker compose exec backend alembic current
```

Expected: `0002 (head)`. Shows which revision the database thinks it's at.

### Show migration history

```bash
docker compose exec backend alembic history
```

Lists all revisions. Useful when you're not sure what's been applied.

### Mark an existing database as up to date

```bash
docker compose exec backend alembic stamp head
```

Marks the DB as already at the latest revision **without running any of
the migration SQL**. Use exactly once when introducing Alembic to a DB
that already has all the tables (created previously via `create_all()`).
Running `upgrade head` instead on such a DB would fail — it would try to
`CREATE TABLE` on tables that already exist.

### Apply pending migrations

```bash
docker compose exec backend alembic upgrade head
```

Actually executes migrations. Use on a **genuinely fresh** database (new
developer machine, CI, clean deployment). Never on the already-stamped
dev database.

### Generate a new migration

```bash
docker compose exec backend alembic revision --autogenerate -m "add column X"
```

Diffs your SQLAlchemy models against the live database schema and
generates a migration file. **Always review the generated file in
`backend/alembic/versions/` before applying.** Autogenerate is a helpful
diff, not a guarantee of correctness.

### Downgrade one revision

```bash
docker compose exec backend alembic downgrade -1
```

Reverts the most recent migration. Use with care — for a schema with
data, downgrades often lose data.

---

## 6. Database Queries (psql)

### List tables

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "\dt"
```

Expected: 5 tables (`alembic_version`, `chunks`, `conversation_turns`,
`documents`, `feedback`).

### Describe a table

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "\d chunks"
```

Shows columns, types, indexes. Useful for confirming a migration landed.

### Count documents by status

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "SELECT status, COUNT(*) FROM documents GROUP BY status;"
```

### List all documents

```bash
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "SELECT filename, status, size_bytes FROM documents ORDER BY created_at DESC LIMIT 20;"
```

`-P pager=off` disables the interactive pager so output prints directly.
Without it, tall output opens in `less` (press `q` to exit).

### Count chunks by modality

```bash
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT c.modality, COUNT(*) AS chunks, AVG(c.token_count)::int AS avg_tokens
FROM chunks c
JOIN documents d ON d.id = c.document_id
GROUP BY c.modality
ORDER BY c.modality;
"
```

Shows how many text/table/image chunks exist. Useful for confirming
multimodal ingestion worked.

### Inspect an image chunk's content

```bash
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT LEFT(content, 400), chunk_metadata->>'image_path'
FROM chunks
WHERE modality = 'image'
LIMIT 3;
"
```

### Find chunks containing a phrase

```bash
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
SELECT d.filename, LEFT(c.content, 120)
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.content ILIKE '%Web Access Symbol%';
"
```

### Delete a specific document

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "DELETE FROM documents WHERE filename = 'sample3.docx';"
```

Cascade deletes its chunks. **Note:** the file on disk stays in
`/app/data/uploads/` — clean separately if you care.

### Delete by status

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "DELETE FROM documents WHERE status='FAILED';"
```

**Enum values are UPPERCASE in Postgres even though Python defines them
lowercase.** Use `'FAILED'`, not `'failed'`.

### Deduplicate documents (keep newest per filename)

```bash
docker compose exec postgres psql -U postgres -d modern_rag -P pager=off -c "
WITH ranked AS (
    SELECT id, filename,
           ROW_NUMBER() OVER (PARTITION BY filename ORDER BY created_at DESC) AS rn
    FROM documents
)
DELETE FROM documents WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
"
```

### Delete a personal/PII document

```bash
docker compose exec postgres psql -U postgres -d modern_rag -c "DELETE FROM documents WHERE filename = 'G Ajay_AccountStatement_28082026_135812.pdf';"
```

**Do this before any commit or demo if you accidentally uploaded
something sensitive.**

---

## 7. Testing

### Run the full test suite (the canonical command)

```bash
docker compose exec backend pytest -v
```

**Expected: 23 passed.** This is the ONLY way to run tests on Windows —
host-side pytest fails with a DLL block (see §11).

### Run one test file

```bash
docker compose exec backend pytest tests/test_phase4_advanced.py -v
```

### Run one specific test

```bash
docker compose exec backend pytest tests/test_phase4_advanced.py::test_deduplicate_removes_near_identical_chunks -v
```

### Run tests matching a keyword

```bash
docker compose exec backend pytest -k "table" -v
```

### Stop at first failure

```bash
docker compose exec backend pytest -x
```

### Run tests directly inside the container shell

```bash
docker compose exec backend bash
cd /app && pytest -v
exit
```

Drops you into a shell inside the container. Useful for interactive
debugging with `pytest` and Python together.

**Do NOT run `pytest` on the Windows host.** It fails on the
`_argkmin.pyd` DLL block. See §11.

---

## 8. Evaluation Harness

### Run the full evaluation

```bash
python eval/run_eval.py
```

Ingests 4–5 sample documents, runs every question in the golden dataset
(20 questions) through both pipelines, saves JSON and Markdown reports
to `eval/results/`.

First run downloads models (~1.2 GB) and takes ~5 minutes. Later runs are
faster.

**Expected summary:**
```
baseline: hit_rate=0.83 ...
improved: hit_rate=0.94 ...
```

### Run with real LLM (not fake) for answer-quality scoring

```bash
python eval/run_eval.py --real-llm
```

Slower, uses the configured LLM provider for generation. Use when you
want answer-quality metrics in addition to retrieval metrics.

### Run with data cleanup disabled

```bash
python eval/run_eval.py --keep-data
```

Keeps the eval corpus documents in the DB after the run. Useful for
inspecting what the harness ingested. **Causes accumulation across runs
— clean up manually after.**

### Regenerate the Markdown report only

```bash
python eval/regenerate_report.py
```

Rebuilds the `.md` report from the most recent JSON results, without
re-running ingestion or the pipelines. Use when the JSON saved but the
Markdown write failed.

### Find the most recent report

```bash
ls -t eval/results/*.md | head -1
cat $(ls -t eval/results/*.md | head -1)
```

`ls -t` sorts by modification time (newest first). `head -1` takes the
first. `cat` prints it.

### List all saved eval runs

```bash
ls -lath eval/results/
```

---

## 9. API Testing with curl

Git Bash handles curl properly — no quoting hell. Every example below
uses Git Bash syntax.

### Health check

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok","app_env":"local","database":"ok"}`

### Upload a document

```bash
curl -X POST "http://localhost:8000/documents" \
  -H "Authorization: Bearer change-me-dev-token" \
  -F "file=@/c/Users/ADMIN/Desktop/rag-platform/_scratch/handbook.docx" \
  -F 'metadata={"department":"hr"}'
```

`curl` determines MIME type from the file extension. Use `;type=` to
override for ambiguous extensions.

### Check document status (poll until ready)

```bash
curl "http://localhost:8000/documents/<id>" \
  -H "Authorization: Bearer change-me-dev-token" \
  | python -m json.tool
```

Replace `<id>` with the document UUID from the upload response.

### List all documents

```bash
curl http://localhost:8000/documents \
  -H "Authorization: Bearer change-me-dev-token" \
  | python -m json.tool
```

`| python -m json.tool` pretty-prints the JSON. Drop it for compact output.

### Query — baseline pipeline

```bash
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}' \
  | python -m json.tool
```

### Query — improved pipeline

```bash
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"How does the deployment pipeline work?","pipeline":"improved"}' \
  | python -m json.tool
```

### Query — with metadata filter

```bash
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved","filters":{"department":"hr"}}' \
  | python -m json.tool
```

### Query — with session_id for follow-ups

```bash
SESSION_ID=$(python -c "import uuid; print(uuid.uuid4())")
echo "Session: $SESSION_ID"

# Turn 1
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What is the leave policy?\",\"pipeline\":\"improved\",\"session_id\":\"$SESSION_ID\"}" \
  | python -m json.tool

# Turn 2 — same session ID
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What about sick leave?\",\"pipeline\":\"improved\",\"session_id\":\"$SESSION_ID\"}" \
  | python -m json.tool
```

Note the escaped quotes inside the double-quoted JSON — needed so
`$SESSION_ID` expands.

### Submit feedback

```bash
curl -X POST "http://localhost:8000/feedback" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"query":"the question","answer":"the answer","is_useful":true}' \
  | python -m json.tool
```

### Measure query wall time

```bash
time curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}' \
  > /dev/null
```

`time` is a bash builtin. `>/dev/null` discards the response body so you
only see timing.

---

## 10. Debugging Diagnostics (Direct Pipeline Introspection)

These bypass the API and call internal functions inside the container.
Useful for isolating exactly which pipeline stage is responsible for an
unexpected result.

### Check raw vector similarity for a query

```bash
docker compose exec backend python -c "
from app.embeddings.provider import get_embedding_provider
from app.retrieval.vector_store import vector_search
from app.db.session import SessionLocal
db = SessionLocal()
embedding = get_embedding_provider().embed_query('your question here')
for r in vector_search(db, embedding, top_k=3):
    print(round(r.score, 4), '|', r.filename, '|', r.content[:60])
"
```

Ignores hybrid and rerank. Shows what the raw vector search sees.
Useful when you suspect the reranker is overruling retrieval.

### Check hybrid and rerank scores side by side

```bash
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
```

Shows the two score scales side by side. Useful for confirming that
reranking is reordering (expected) vs. gating (bug).

### See what multi-query expansion generates

```bash
docker compose exec backend python -c "
from app.generation.providers import get_llm_client
from app.retrieval.query_transform import expand_queries
print(expand_queries(get_llm_client(), 'PTO accrual amount'))
"
```

Shows the actual paraphrases the LLM produces. Useful for confirming
multi-query fires and for understanding why jargon isn't bridged.

### Test the Gemini → Ollama fallback

```bash
# Temporarily set GEMINI_API_KEYS to invalid values in .env, then:
docker compose up -d backend

# Run any query — it should still succeed via Ollama
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"baseline"}' \
  | python -m json.tool

# Check the logs for the fallback message
docker compose logs backend --tail=20 | grep "falling_back"

# Restore real keys and restart
docker compose up -d backend
```

### Inspect the raw chunks table for a document

```bash
docker compose exec backend python -c "
from app.db.session import SessionLocal
from app.db.models import Chunk, Document
db = SessionLocal()
doc = db.query(Document).filter(Document.filename == 'sample3.docx').order_by(Document.created_at.desc()).first()
for c in db.query(Chunk).filter(Chunk.document_id == doc.id).order_by(Chunk.chunk_index):
    print(f'{c.chunk_index:3d} | {c.modality:6s} | {c.token_count:4d} | {c.content[:60]!r}')
db.close()
"
```

Shows every chunk from a document with its modality and token count.
Useful for spotting heading-only fragments or missing content.

---

## 11. Environment-Specific Fixes

### Windows Application Control blocks host-side pytest

If you see:

```
ImportError: DLL load failed while importing _argkmin:
An Application Control policy has blocked this file.
```

**Do not try to fix it.** Run tests in Docker instead:

```bash
docker compose exec backend pytest -v
```

The container is Linux. No such policy. Same environment the app runs in.

### Port 5432 collision (Windows)

Symptom: `password authentication failed` or `type "vector" does not
exist` when connecting to `localhost:5432`.

Diagnose:

```bash
netstat -ano | findstr :5432
Get-Process -Id <pid>
```

If you see two PIDs on the same port, a native Windows Postgres and
Docker's forwarder are fighting. Fix: either stop the native Postgres,
or confirm `.env`'s `DATABASE_URL` uses `localhost:5433` (the Docker
port).

### Docling `OfflineModeIsEnabled` on first parse

Symptom: first PDF parse fails with `Cannot reach https://huggingface.co`.

Cause: `HF_HUB_OFFLINE=1` blocks the model download.

Fix: temporarily set `HF_HUB_OFFLINE=0` in `docker-compose.yml`, run one
parse, then flip it back to `1`. Models cache in `hf_cache` and stay.

```bash
# Edit docker-compose.yml
docker compose up -d backend
docker compose exec backend python -c "
from docling.document_converter import DocumentConverter
import os
target = os.path.join('/app/data/uploads', [f for f in os.listdir('/app/data/uploads') if f.endswith('.pdf')][0])
DocumentConverter().convert(target)
print('cached')
"
# Flip back to 1 in docker-compose.yml
docker compose up -d backend
```

### Git Bash path mangling

If a command like `docker compose exec backend python /app/../eval/run_eval.py`
fails with a Windows path error, Git Bash is converting the Unix path.
Fix: prefix with `MSYS_NO_PATHCONV=1`:

```bash
MSYS_NO_PATHCONV=1 docker compose exec backend python /app/some/path
```

Or just use paths that are valid **inside** the container (starting with
`/app/`), never host paths.

### Model download interrupted — meta tensor error

Symptom: `NotImplementedError: Cannot copy out of meta tensor; no data!`

Cause: model download interrupted (VPN, firewall, flaky connection).

Fix: delete the cache and rebuild:

```bash
docker compose down -v
docker compose up --build
```

---

## 12. Git Operations

### Check what's changed

```bash
git status
```

### Show recent commits

```bash
git log --oneline -10
```

### Stage specific files (preferred)

```bash
git add HLD.md LLD.md frontend/app.py
```

### Stage everything not gitignored

```bash
git add -A
```

### ⚠️ CRITICAL: verify `.env` is not staged

```bash
git check-ignore .env
```

Expected: prints `.env`. If nothing prints, `.env` is NOT ignored and
WILL be committed. Stop and fix `.gitignore`.

### Review what's about to be committed

```bash
git status
```

Read the file list carefully. `.env` must NOT appear.

### Unstage a file

```bash
git restore --staged .env
```

### Commit

```bash
git commit -m "Your message here"
```

### Push

```bash
git push
```

If it prompts for a password, paste your **Personal Access Token**
(`ghp_...`), not your GitHub password. Generate one at
https://github.com/settings/tokens — scope `repo`.

### Pull before pushing

```bash
git pull --rebase
git push
```

Use when `git push` is rejected because GitHub has commits you don't
have locally.

### Create a tag

```bash
git tag text-only-baseline
git push origin text-only-baseline
```

Tags are bookmarks. Useful as safety nets before big changes.

### Restore a file from a tag

```bash
git checkout text-only-baseline -- backend/app/ingestion/parsers.py
```

### Restore everything from a tag

```bash
git checkout text-only-baseline
```

---

## 13. Ollama Commands

### List locally downloaded models

```bash
curl -s http://localhost:11434/api/tags | python -m json.tool
```

Or if the `ollama` CLI is on PATH:

```bash
ollama list
```

### Pull a model

```bash
ollama pull moondream:1.8b
ollama pull qwen2.5:7b
ollama pull llama3.2:3b
```

### Remove a model

```bash
ollama rm llama3.2:3b
```

### Check if Ollama is running

```bash
curl -s http://localhost:11434/api/tags > /dev/null && echo "Ollama up" || echo "Ollama down"
```

### Test Ollama reachability from inside the container

```bash
docker compose exec backend curl -s http://host.docker.internal:11434/api/tags
```

If this fails but the host-side curl works, add to `docker-compose.yml`
under the backend service:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Then `docker compose up -d backend`.

### Start Ollama as a background service

```bash
ollama serve
```

Blocks the terminal. Run in a separate window and leave it open.

---

## 14. Cleanup

### Remove Python caches

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
```

### Remove dangling Docker images

```bash
docker image prune -f
```

### Remove stopped containers

```bash
docker container prune -f
```

### Show Docker disk usage

```bash
docker system df
```

### Full Docker cleanup (aggressive)

```bash
docker system prune -a
```

Removes everything not in use. **This will remove the Postgres volume if
containers are stopped.** Do not run casually.

### Delete a specific file from the upload volume

```bash
docker compose exec backend rm /app/data/uploads/<uuid>.pdf
```

---

## 15. Quick Reference Table

| Command | Purpose |
|---|---|
| `cd /c/Users/ADMIN/Desktop/rag-platform` | Move to repo root (Git Bash) |
| `docker compose build backend` | Rebuild image after code changes |
| `docker compose up -d` | Start containers, pick up `.env` changes |
| `docker compose down` | Stop containers, keep data |
| `docker compose down -v` | Stop containers, wipe all data |
| `docker compose logs backend -f` | Live log tail |
| `docker compose exec backend <cmd>` | Run something inside the container |
| `docker compose exec backend pytest -v` | Run the full test suite |
| `docker compose exec backend alembic current` | Check DB migration state |
| `docker compose exec backend alembic upgrade head` | Apply migrations |
| `docker compose exec postgres psql -U postgres -d modern_rag -c "<sql>"` | Query the DB |
| `python eval/run_eval.py` | Run the evaluation harness |
| `ls -t eval/results/*.md \| head -1` | Find latest eval report |
| `curl ... http://localhost:8000/query` | Call the query API |
| `git check-ignore .env` | Verify `.env` won't be committed |
| `git add <files> && git commit -m "..." && git push` | Commit and push |
| `ollama pull moondream:1.8b` | Download a vision model |
| `docker stats --no-stream` | Show container resource usage |
| `docker compose logs backend --tail=200 \| grep "pattern"` | Search logs |

---

## 16. Canonical Workflow (The Three Commands You'll Run Most)

```bash
# 1. Rebuild after any backend change
docker compose build backend && docker compose up -d

# 2. Run tests
docker compose exec backend pytest -v

# 3. Ask a question and pretty-print
curl -s -X POST "http://localhost:8000/query" \
  -H "Authorization: Bearer change-me-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the leave policy?","pipeline":"improved"}' \
  | python -m json.tool
```

Everything else in this file is either one-time setup, a debugging aid,
or a reference for when something goes wrong.

---

## 17. Common Error Messages and What They Mean

| Error | Cause | Fix |
|---|---|---|
| `password authentication failed for user "rag"` | Wrong `.env` password, or connecting to native Postgres on 5432 | Check `.env`, use port 5433 |
| `type "vector" does not exist` | Connected to native Postgres (no pgvector) | Use port 5433 (Docker's Postgres) |
| `Cannot copy out of meta tensor; no data!` | Interrupted model download | `docker compose down -v && docker compose up --build` |
| `DLL load failed while importing _argkmin` | Windows Application Control blocks a scikit-learn binary | `docker compose exec backend pytest -v` instead |
| `OfflineModeIsEnabled` (Docling) | `HF_HUB_OFFLINE=1` blocks first download | Set to `0`, run one parse, back to `1` |
| `no changes added to commit` | Ran `git commit` without `git add` first | `git add <files>` then commit |
| `Updates were rejected` (git push) | GitHub has commits you don't | `git pull --rebase` then push |
| `invalid input value for enum document_status: "failed"` | Lowercase in raw SQL | Use `'FAILED'` |
| `st.session_state has no attribute "pipeline"` | Read from a background thread | Capture on main thread first (see `DESIGN.md` §11) |
| `StreamlitInvalidColumnSpecError` | `st.columns([1, 0])` — zero is invalid | Use only positive widths |
```

---

Save at `docs/COMMANDS.md`, then commit:

```bash
cd /c/Users/ADMIN/Desktop/rag-platform
git add docs/COMMANDS.md
git commit -m "Docs: add comprehensive commands reference"
git push
```

Your `docs/` folder now has the complete set: **PRD** (what and why), **ARCHITECTURE** (system layout), **DESIGN** (why each choice), **RULES** (invariants), **MEMORY** (war stories), **TASKS** (current state), and **COMMANDS** (every command with its use case). Together with `README.md`, `HLD.md`, and `LLD.md` at the root, anyone — human or agent — can pick this project up cold.