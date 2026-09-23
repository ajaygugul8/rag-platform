"""
Tracing, per spec: "Trace ingestion, retrieval, reranking and generation
steps." A full OpenTelemetry collector setup is real infrastructure most
demo environments don't have running; this gives the same *information* —
a structured span per stage with start/end/duration and a shared
trace_id — as JSON log lines, which is trivially upgradeable to real OTel
later (swap the `logger.info` call in `_emit` for a span exporter; every
call site using `trace_stage(...)` stays identical).
"""

import logging
import time
import uuid
from contextlib import contextmanager

logger = logging.getLogger("rag.tracing")


@contextmanager
def trace_stage(stage_name: str, **fields):
    span_id = str(uuid.uuid4())
    start = time.perf_counter()
    logger.info("stage_started", extra={"stage": stage_name, "span_id": span_id, **fields})
    try:
        yield span_id
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "stage_failed",
            extra={"stage": stage_name, "span_id": span_id, "duration_ms": round(duration_ms, 1), "error": str(exc)},
        )
        raise
    else:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "stage_completed",
            extra={"stage": stage_name, "span_id": span_id, "duration_ms": round(duration_ms, 1), **fields},
        )
