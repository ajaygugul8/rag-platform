import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.feedback import router as feedback_router
from app.api.query import router as query_router
from app.api.schemas import HealthResponse
from app.config import settings
from app.core.exceptions import RagPlatformError
from app.db.session import SessionLocal
from app.observability.logging import configure_logging

configure_logging()
logger = logging.getLogger("rag.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema management is now Alembic's job (backend/alembic/), not
    # create_all() - see backend/alembic/versions/0001_initial_schema.py
    # for why: create_all() only ever adds new tables, silently doing
    # nothing when an EXISTING table needs a new column - which caused a
    # real production-adjacent bug (chunks.content_tsv missing after a
    # schema change, discovered only when a query crashed). Run
    # `alembic upgrade head` before starting the app (see README), not
    # here at import time - migrations should be an explicit, reviewable
    # deploy step, not something that silently runs on every container
    # start.
    logger.info("startup_complete", extra={"app_env": settings.app_env})
    yield
    logger.info("shutdown_complete")


app = FastAPI(
    title="Modern RAG Platform",
    version="0.1.0",
    description="Production-style Retrieval-Augmented Generation platform.",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attaches a request_id to every request and logs latency — the
    minimal observability every route gets for free, per the spec's
    'log latency ... without logging secrets' requirement."""
    request_id = str(uuid.uuid4())
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


@app.exception_handler(RagPlatformError)
async def domain_error_handler(request: Request, exc: RagPlatformError) -> JSONResponse:
    """Every domain exception becomes a clean 4xx/5xx JSON body instead of a
    raw traceback — required so the API never leaks internals to clients."""
    logger.warning("domain_error", extra={"error_type": type(exc).__name__, "detail": str(exc)})
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    db_status = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — health check must never crash the process
        logger.error("health_check_db_failed", extra={"error": str(exc)})
        db_status = "unreachable"

    return HealthResponse(status="ok", app_env=settings.app_env, database=db_status)


app.include_router(documents_router)
app.include_router(query_router)
app.include_router(feedback_router)
app.include_router(conversations_router)
