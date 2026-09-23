"""
Structured JSON logging. Every log line is a JSON object so it can be
shipped to any log aggregator (Loki, CloudWatch, Datadog) without a custom
parser. This is the foundation Phase 6 builds tracing/metrics on top of.

Rule enforced by convention (and reviewed in code review, not code): never
pass request bodies, API keys, or file contents into `extra=`. Only IDs,
statuses, durations and counts.
"""

import json
import logging
import sys
from datetime import datetime, timezone

from app.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include any structured fields passed via `extra=`.
        standard_keys = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
        for key, value in record.__dict__.items():
            if key not in standard_keys and key != "message":
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # Quiet noisy third-party loggers at INFO.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
