from functools import lru_cache

from app.config import settings
from app.embeddings.base import EmbeddingProvider


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        from app.embeddings.openai_provider import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider()

    from app.embeddings.local import LocalEmbeddingProvider

    return LocalEmbeddingProvider()
