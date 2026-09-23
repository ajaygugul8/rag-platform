from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Interface every embedding backend implements. The rest of the
    platform only ever depends on this — swapping local <-> OpenAI <->
    anything else is a one-line config change (`EMBEDDING_PROVIDER`)."""

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of chunk texts for storage."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string at retrieval time. Some models
        (e.g. BGE) use a different prefix/instruction for queries vs
        documents, which is why this is a separate method rather than
        reusing embed_documents([text])[0]."""
