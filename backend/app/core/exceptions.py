class RagPlatformError(Exception):
    """Base class for all domain errors. Caught centrally in main.py's
    exception handler so API responses are consistent and never leak
    stack traces or secrets to clients."""


class UnsupportedFileTypeError(RagPlatformError):
    pass


class FileTooLargeError(RagPlatformError):
    pass


class IngestionError(RagPlatformError):
    """Raised when a document fails to parse/clean/chunk. Ingestion failures
    must be handled gracefully per spec — this exception carries the
    document_id so the caller can mark that document's status as FAILED
    instead of crashing the whole batch."""

    def __init__(self, document_id: str, message: str):
        self.document_id = document_id
        super().__init__(f"[document={document_id}] {message}")


class RetrievalError(RagPlatformError):
    pass


class GenerationError(RagPlatformError):
    pass
