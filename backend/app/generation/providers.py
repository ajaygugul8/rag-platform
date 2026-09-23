"""
LLM provider selection: Gemini is the default/primary provider, with
support for multiple API keys (e.g. several free-tier keys, each with
their own quota) - every key is tried in order before giving up on
Gemini entirely. If ALL Gemini keys fail for any reason (missing/invalid
key, quota exceeded, network error, service outage), generation
automatically falls back to a local Ollama model instead of hard-failing
the whole request.

Both Gemini and Ollama expose an OpenAI-compatible chat completions API,
so one thin client class handles both, and handles each individual
Gemini key too - only base_url, api_key, and model differ between
instances.
"""

import logging
from functools import lru_cache

from app.config import settings
from app.core.exceptions import GenerationError
from app.generation.llm_client import LLMClient

logger = logging.getLogger("rag.generation.providers")


class _OpenAICompatibleClient(LLMClient):
    """Thin wrapper around any OpenAI-compatible chat completions endpoint.
    Gemini and Ollama both qualify - only construction args differ."""

    def __init__(self, base_url: str, api_key: str, model: str, label: str):
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._label = label  # for error messages/logs only, never logged with content

    def _log_usage(self, resp) -> None:
        """Log token usage if the provider exposed it. Silent no-op otherwise."""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if prompt_tokens is None and completion_tokens is None:
            return
        logger.info(
            "llm_usage",
            extra={
                "provider": self._label,
                "model": self._model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # low temperature - grounded answers, not creative ones
            )
            self._log_usage(resp)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            raise GenerationError(f"{self._label} generation failed: {exc}") from exc


class FallbackLLMClient(LLMClient):
    """Tries `primary` first. On ANY exception, logs a warning and retries
    the same prompt against `fallback`. If fallback also fails, that
    exception propagates normally."""

    def __init__(self, primary: LLMClient, fallback: LLMClient):
        self._primary = primary
        self._fallback = fallback

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            return self._primary.generate(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning(
                "primary_llm_failed_falling_back_to_ollama", extra={"error": str(exc)}
            )
            return self._fallback.generate(system_prompt, user_prompt)


@lru_cache
def get_llm_client() -> LLMClient:
    ollama = _OpenAICompatibleClient(
        base_url=settings.ollama_base_url,
        api_key="ollama",  # Ollama ignores this value but the SDK requires a non-empty string
        model=settings.ollama_model,
        label="Ollama",
    )

    keys = [k.strip() for k in settings.gemini_api_keys.split(",") if k.strip()]
    if not keys:
        logger.warning("no_gemini_keys_configured_using_ollama_only")
        return ollama

    gemini_clients = [
        _OpenAICompatibleClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=key,
            model=settings.gemini_model,
            label=f"Gemini (key {index + 1}/{len(keys)})",
        )
        for index, key in enumerate(keys)
    ]

    # Chain: key[0] -> key[1] -> ... -> key[N-1] -> ollama.
    chain: LLMClient = ollama
    for client in reversed(gemini_clients):
        chain = FallbackLLMClient(primary=client, fallback=chain)
    return chain