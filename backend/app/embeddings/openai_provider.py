from app.config import settings
from app.embeddings.base import EmbeddingProvider

_OPENAI_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model: str = "text-embedding-3-small"):
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = model

    @property
    def dimension(self) -> int:
        return _OPENAI_DIMENSIONS.get(self._model, 1536)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
