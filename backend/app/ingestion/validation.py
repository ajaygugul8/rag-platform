from app.config import settings
from app.core.exceptions import FileTooLargeError, UnsupportedFileTypeError

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


def validate_upload(filename: str, content_type: str, size_bytes: int) -> None:
    """Validate file type and size before anything touches disk or the DB.
    Cheap checks first — never let a 2GB file reach the parser."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(
            f"'{content_type}' is not supported. Allowed: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise FileTooLargeError(
            f"File is {size_bytes / (1024 * 1024):.1f}MB, exceeds the {settings.max_upload_mb}MB limit."
        )
