# Terminal Command Reference — Modern RAG Platform

Every command needed to set up, run, test, debug, and evaluate this
project, organized by task. Shell examples are PowerShell (Windows) since
that's this project's environment; Docker commands themselves are
identical on any OS.

---

## 1. First-Time Setup

```powershell
cd C:\Users\ADMIN\Desktop\rag-platform
```
Move into the project root. **Almost every command below must be run from
here** — `docker compose` looks for `docker-compose.yml` in your current
directory (it does search parent directories if not found, but don't rely
on that).

```powershell
cp .env.example .env
```
Create your local environment file from the template. Edit it afterward to
set at least `GEMINI_API_KEYS` (comma-separated, no spaces) — everything
else has a working default.

```powershell
docker compose build backend
```
Build the backend Docker image from `backend/Dockerfile` and
`backend/requirements.txt`. **Run this after any change to backend source
code** — `docker compose up` alone does NOT re-read your files, it only
starts/recreates containers from whatever image already exists.

```powershell
docker compose build --no-cache backend
```
Same as above, but ignores Docker's layer cache entirely. Use this when a
code change doesn't seem to take effect after a normal build — it's slower
(full reinstall of dependencies) but guarantees nothing stale is reused.

```powershell
docker compose up -d
```
Start all containers (Postgres + backend) in the background (`-d` =
detached). If images already exist, this does NOT rebuild them — pair with
`build` first if you changed code.

```powershell
docker compose up --build -d
```
Build (only if needed) and start, combined into one command.

---

## 2. Daily Docker Operations

```powershell
docker compose ps
```
List all containers and their status. Look for `healthy` next to
`rag_postgres` and `rag_backend` before assuming the stack is ready.

```powershell
docker compose logs backend --tail=50
```
Show the last 50 log lines from the backend container. The first thing to
check whenever something behaves unexpectedly.

```powershell
docker compose logs backend -f
```
Follow backend logs live as new requests come in. `Ctrl+C` to stop
following (does not stop the container).

```powershell
docker compose down
```
Stop and remove containers. **Data volumes (Postgres data, uploaded files,
the HuggingFace model cache) are preserved** — safe to run anytime.

```powershell
docker compose down -v
```
Stop and remove containers **AND delete all data volumes** — wipes the
database (all documents/chunks/feedback gone) and the cached embedding/
reranker models (next start re-downloads them). Only use this when you
genuinely want a clean slate, e.g. to fix a schema-drift error on a
disposable dev database.

---

## 3. Running Commands Inside the Container

```powershell
docker compose exec backend <command>
```
Run any command inside the already-running backend container. Used
throughout this project for verification and debugging — some concrete
examples:

```powershell
docker compose exec backend grep -n "^class " /app/app/generation/providers.py
```
Confirm which Python classes actually exist inside the **running
container** right now — the single most useful command for catching "I
edited the file but the container never got rebuilt" mistakes, which
happened repeatedly during this project's development.

```powershell
docker compose exec backend python -c "from app.config import settings; print(settings.enable_multi_query)"
```
Print a live config value from inside the container, to confirm an `.env`
change actually took effect.

```powershell
docker compose exec backend python -c "import app.generation.providers; print('imports fine')"
```
Quick syntax/import sanity check for one file — fails fast with a clear
traceback if there's a Python error, before you waste time on a full query
test.

```powershell
Get-Content eval\run_eval.py | Select-String "write_text"
```
(Runs on your **host**, not in the container.) Confirm a specific text edit
is actually present in a file on disk before assuming a fix landed.

---

## 4. Database Migrations (Alembic)

```powershell
docker compose exec backend alembic current
```
Show which migration revision the database currently thinks it's at.
Expect `0001 (head)` right after the initial setup.

```powershell
docker compose exec backend alembic stamp head
```
Mark an **existing** database as already being at the latest revision,
**without running any of the migration's SQL**. Use this exactly once, the
first time Alembic is introduced to a database that already has all the
tables (created previously via `create_all()`). Running `upgrade head`
instead on such a database would fail — it would try to `CREATE TABLE` on
tables that already exist.

```powershell
docker compose exec backend alembic upgrade head
```
Actually execute all pending migrations. Use this on a **genuinely fresh**
database (new developer machine, CI, a clean deployment) — never on the
already-stamped dev database, or after `stamp head` has already been run.

```powershell
docker compose exec backend alembic revision --autogenerate -m "add new column"
```
Generate a new migration file by diffing your SQLAlchemy models
(`app/db/models.py`) against the live database schema. Run this every time
you change a model. **Always review the generated file before applying
it** — autogenerate is a helpful diff, not a guarantee of correctness.

---

## 5. Backend Tests

```powershell
docker compose up -d postgres
```
Tests need a real Postgres instance (vector columns don't have a faithful
mock) — start just the database, not the full stack.

```powershell
cd backend
pip install -r requirements.txt
```
Install Python dependencies locally (outside Docker) so `pytest` can
import the application code directly.

```powershell
pytest -v
```
Run the full test suite with verbose per-test output.

```powershell
pytest tests/test_phase4_advanced.py -v
```
Run just one test file — useful when iterating on a specific area.

---

## 6. Evaluation Harness (Phase 5)

```powershell
cd C:\Users\ADMIN\Desktop\rag-platform
python eval/run_eval.py
```
Run the full evaluation: ingest the sample document corpus, run every
question in the golden dataset through **both** pipelines (`baseline` and
`improved`), save a JSON and Markdown report to `eval/results/`. First run
downloads two models (~1.2GB combined) and takes several minutes; later
runs are much faster since models are cached.

```powershell
python eval/regenerate_report.py
```
Regenerate just the Markdown report from the most recent saved JSON
results, without re-running ingestion or the pipelines. Use this whenever
the JSON saved successfully but the Markdown write step failed for any
reason — saves re-running the slow part just to fix a report format issue.

```powershell
Get-ChildItem eval\results\*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
```
Find the most recent eval report file without needing to remember its
timestamp-based filename.

---

## 7. Frontend

```powershell
pip install streamlit requests
```
Install the frontend's two dependencies (it's a pure HTTP client — no
database or model libraries needed on this side).

```powershell
streamlit run frontend/app.py
```
Launch the chat UI. Opens automatically at `http://localhost:8501`. The
backend (`docker compose up -d`) must already be running — the frontend
has no functionality of its own without it.

---

## 8. API Testing (PowerShell)

Use `Invoke-RestMethod`, not `curl.exe` — PowerShell's `curl.exe` mangles
JSON body quoting in ways that are more trouble than they're worth (this
was learned the hard way early in the project).

**Health check:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
```

**Reusable upload helper** (paste once per PowerShell session, or save to
a `.ps1` file and dot-source it):
```powershell
Add-Type -AssemblyName System.Net.Http

function Upload-Document {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string]$Metadata = '{}',
        [string]$ApiUrl = "http://localhost:8000/documents",
        [string]$Token = "change-me-dev-token"
    )
    if (-not (Test-Path $FilePath)) { Write-Error "File not found: $FilePath"; return }

    $extension = [System.IO.Path]::GetExtension($FilePath).ToLower()
    $mimeMap = @{
        ".pdf"  = "application/pdf"
        ".docx" = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ".txt"  = "text/plain"
        ".md"   = "text/markdown"
    }
    $contentType = $mimeMap[$extension]
    if (-not $contentType) { Write-Error "Unsupported file type '$extension'"; return }

    $client = New-Object System.Net.Http.HttpClient
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)
    $content = New-Object System.Net.Http.MultipartFormDataContent
    $fileStream = [System.IO.File]::OpenRead($FilePath)
    $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
    $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse($contentType)
    $content.Add($fileContent, "file", [System.IO.Path]::GetFileName($FilePath))
    $content.Add((New-Object System.Net.Http.StringContent($Metadata)), "metadata")

    $response = $client.PostAsync($ApiUrl, $content).Result
    $result = $response.Content.ReadAsStringAsync().Result | ConvertFrom-Json
    $fileStream.Dispose(); $client.Dispose()
    return $result
}
```

**Upload a document:**
```powershell
Upload-Document -FilePath "C:\path\to\file.pdf" -Metadata '{"department":"hr"}'
```

**Check a document's ingestion status** (poll until `status` is `ready`):
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/documents/<document-id>" -Method Get `
  -Headers @{ Authorization = "Bearer change-me-dev-token" }
```

**List all documents:**
```powershell
$docs = Invoke-RestMethod -Uri "http://localhost:8000/documents" -Method Get `
  -Headers @{ Authorization = "Bearer change-me-dev-token" }
$docs | Format-List filename, status, id
```

**Query — baseline pipeline:**
```powershell
$body = @{ question = "your question here"; pipeline = "baseline" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
  -Headers @{ Authorization = "Bearer change-me-dev-token" } `
  -ContentType "application/json" -Body $body
```

**Query — improved pipeline, with a metadata filter:**
```powershell
$body = @{
    question = "your question here"
    pipeline = "improved"
    filters  = @{ department = "hr" }
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
  -Headers @{ Authorization = "Bearer change-me-dev-token" } `
  -ContentType "application/json" -Body $body
```

**Query — with conversation memory (follow-up questions):**
```powershell
$sessionId = [guid]::NewGuid().ToString()
$body = @{ question = "your question here"; pipeline = "improved"; session_id = $sessionId } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
  -Headers @{ Authorization = "Bearer change-me-dev-token" } `
  -ContentType "application/json" -Body $body
# re-run with the SAME $sessionId and a follow-up question to test rewriting
```

**Submit feedback:**
```powershell
$body = @{ query = "the question asked"; answer = "the answer given"; is_useful = $true } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/feedback" -Method Post `
  -Headers @{ Authorization = "Bearer change-me-dev-token" } `
  -ContentType "application/json" -Body $body
```

**See a query's real error message instead of a generic wrapper**
(`Invoke-RestMethod` hides the response body on non-2xx by default):
```powershell
try {
    Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
      -Headers @{ Authorization = "Bearer change-me-dev-token" } `
      -ContentType "application/json" -Body $body
}
catch { $_.ErrorDetails.Message }
```

---

## 9. Debugging Diagnostics (direct pipeline introspection)

These bypass the API entirely and call internal functions directly inside
the container — useful for isolating exactly which pipeline stage is
responsible for an unexpected result.

**Check raw vector similarity for a query, ignoring hybrid/rerank:**
```powershell
docker compose exec backend python -c "
from app.embeddings.provider import get_embedding_provider
from app.retrieval.vector_store import vector_search
from app.db.session import SessionLocal
db = SessionLocal()
provider = get_embedding_provider()
embedding = provider.embed_query('your question here')
for r in vector_search(db, embedding, top_k=3):
    print(round(r.score, 4), '|', r.filename, '|', r.content[:60])
"
```

**Check hybrid search scores AND reranker scores side by side:**
```powershell
docker compose exec backend python -c "
from app.embeddings.provider import get_embedding_provider
from app.retrieval.hybrid import hybrid_search
from app.retrieval.reranker import rerank
from app.db.session import SessionLocal
db = SessionLocal()
q = 'your question here'
embedding = get_embedding_provider().embed_query(q)
candidates = hybrid_search(db, q, embedding, top_k=10)
print('--- hybrid scores ---')
for c in candidates: print(round(c.score, 4), '|', c.filename)
reranked = rerank(q, candidates, top_n=4)
print('--- reranker scores ---')
for c in reranked: print(round(c.score, 4), '|', c.filename)
"
```

**See exactly what multi-query expansion generates for a question:**
```powershell
docker compose exec backend python -c "
from app.generation.providers import get_llm_client
from app.retrieval.query_transform import expand_queries
client = get_llm_client()
print(expand_queries(client, 'your question here'))
"
```

**Measure cache hit vs. miss latency directly:**
```powershell
$body = @{ question = "your question here"; pipeline = "improved" } | ConvertTo-Json
Measure-Command {
    Invoke-RestMethod -Uri "http://localhost:8000/query" -Method Post `
      -Headers @{ Authorization = "Bearer change-me-dev-token" } `
      -ContentType "application/json" -Body $body
} | Select-Object TotalMilliseconds
# run the exact same command again immediately - a cache hit drops from
# ~1-2 seconds to under 50ms
```

**Test the Gemini-to-Ollama fallback chain actually works:**
```powershell
# temporarily point GEMINI_API_KEYS at invalid values in .env, then:
docker compose up -d
# run any query - it should still succeed (via Ollama), and:
docker compose logs backend --tail=20
# should show "primary_llm_failed_falling_back_to_ollama" warnings
# then restore your real key(s) in .env and `docker compose up -d` again
```

---

## Quick Reference: Command → Purpose

| Command | Purpose |
|---|---|
| `docker compose build backend` | Rebuild image after code changes |
| `docker compose up -d` | Start containers |
| `docker compose down` | Stop containers (keep data) |
| `docker compose down -v` | Stop containers, wipe all data |
| `docker compose logs backend -f` | Live log tail |
| `docker compose exec backend <cmd>` | Run something inside the container |
| `docker compose exec backend alembic current` | Check DB migration state |
| `docker compose exec backend alembic stamp head` | Mark existing DB as up to date |
| `docker compose exec backend alembic upgrade head` | Apply migrations (fresh DB only) |
| `pytest -v` | Run backend tests |
| `python eval/run_eval.py` | Run full evaluation |
| `python eval/regenerate_report.py` | Rebuild eval report from saved data |
| `streamlit run frontend/app.py` | Launch the chat UI |
| `Invoke-RestMethod ...` | Call the API directly (see §8) |
