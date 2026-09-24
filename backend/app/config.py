"""
Centralized configuration.

Design principle: NOTHING in this codebase reads os.environ directly outside
this file. Every module imports `settings` from here. This is what makes the
platform's non-functional requirement ("configuration through environment
variables; secrets must never be hard-coded") actually enforceable — there's
exactly one place secrets can leak from, and it's easy to audit.
"""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_env: str = "local"
    log_level: str = "INFO"
    max_upload_mb: int = 25
    upload_dir: str = "./data/uploads"

    # --- Database ---
    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"

    # --- Embeddings ---
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # --- LLM: Gemini is the default/primary provider; Ollama is the
    # automatic fallback if EVERY Gemini key fails for any reason
    # (missing/invalid key, quota exceeded, network error). Multiple
    # comma-separated keys let several free-tier keys (each with their own
    # quota) behave collectively like one higher-quota key — each is tried
    # in order before falling through to Ollama. openai_api_key below is
    # unrelated to this — it's only used if EMBEDDING_PROVIDER=openai.
    gemini_api_keys: str = ""  # comma-separated: "key1,key2,key3"
    gemini_model: str = "gemini-flash-latest"
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_model: str = "qwen3:8b"
    openai_api_key: str | None = None  # used only by embeddings/openai_provider.py
    # --- Vision (Phase 4: image description at ingestion) ---
    vision_enabled: bool = True
    ollama_vision_model: str = "moondream:1.8b"
    vision_max_tokens: int = 60

    # --- Retrieval ---
    retrieval_top_k: int = 8
    hybrid_alpha: float = 0.5
    rerank_enabled: bool = True
    rerank_top_n: int = 4
    enable_multi_query: bool = False
    context_token_budget: int = 2000
    conversation_history_turns: int = 6

    # --- Security ---
    api_auth_token: str = "change-me-dev-token"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — settings are read once per process."""
    return Settings()


settings = get_settings()