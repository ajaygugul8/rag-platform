"""
Local embedding provider using sentence-transformers. Model is loaded
lazily and cached at module level so it's loaded once per process, not
once per request — loading a transformer model takes seconds, doing that
per-request would make every query multi-second before retrieval even
starts.

BGE models were trained with an instruction prefix for queries (but not
for documents) — omitting it measurably hurts retrieval quality, which is
exactly the kind of detail that's invisible until you check the model
card. Baking it in here means callers never need to know.
"""

from functools import lru_cache

from app.config import settings
from app.embeddings.base import EmbeddingProvider

_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache
def _load_model():
    from sentence_transformers import SentenceTransformer

    # `low_cpu_mem_usage=False` forces the normal (non-meta-device) load
    # path. Newer transformers/accelerate versions default to loading
    # weights onto a "meta" device first and materializing them in place,
    # which throws "Cannot copy out of meta tensor; no data!" if the
    # download was ever interrupted/partial — a real risk on flaky or
    # firewalled networks. This is slightly slower but never hits that
    # failure mode. device="cpu" is explicit so this never silently tries
    # to use a GPU that isn't there in this container.
    return SentenceTransformer(
        settings.embedding_model,
        device="cpu",
        model_kwargs={"low_cpu_mem_usage": False},
    )


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimension: int | None = None):
        self._dimension = dimension or settings.embedding_dim

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = _load_model()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        model = _load_model()
        vector = model.encode(_QUERY_INSTRUCTION + text, normalize_embeddings=True, show_progress_bar=False)
        return vector.tolist()