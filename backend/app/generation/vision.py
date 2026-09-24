"""
Vision-based image description for multimodal ingestion.

Kept separate from app.generation.providers — that module implements the
frozen LLMClient interface (generate(system, user) -> str), which is
text-only by contract. Vision needs to pass image bytes alongside the
prompt, so it lives here with its own small interface.

Backed by Ollama's OpenAI-compatible endpoint. moondream:1.8b is the
default — 1.7 GB, ~5–15s per image on CPU. Swap to a larger vision model
(qwen2.5-vl:7b, llava:7b) via OLLAMA_VISION_MODEL if quality is
insufficient.

On any failure (network, model missing, malformed response), describe_image
returns an empty string and logs a warning. Ingestion never fails because
one image couldn't be described — a document with no description is still
useful, a document that fails to ingest is not.
"""

import base64
import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger("rag.generation.vision")

DEFAULT_PROMPT = (
    "In ONE short sentence (maximum 20 words), state what this image "
    "depicts. Include any visible text. Do not describe colors, "
    "backgrounds, or layout unless they are the subject. "
    "Do not start with 'This image shows' — just state the subject."
)

def _trim_to_one_sentence(text: str) -> str:
    """Keep only the first sentence. Vision models routinely ignore
    length instructions; this enforces the constraint deterministically."""
    text = text.strip()
    if not text:
        return ""
    # Split on sentence-ending punctuation, keep the first non-empty part
    for sep in (". ", "! ", "? "):
        if sep in text:
            first = text.split(sep, 1)[0]
            return (first + sep[0]).strip()
    if text.endswith((".", "!", "?")):
        return text
    return text + "."
    
class VisionError(Exception):
    pass


class _OllamaVisionClient:
    def __init__(self, base_url: str, model: str):
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key="ollama")
        self._model = model

    def describe(self, image_bytes: bytes, prompt: str = DEFAULT_PROMPT) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
                max_tokens=settings.vision_max_tokens,
                temperature=0.1,
            )
            raw = (resp.choices[0].message.content or "").strip()
            return _trim_to_one_sentence(raw)
        except Exception as exc:
            raise VisionError(f"Vision description failed: {exc}") from exc


@lru_cache
def get_vision_client() -> _OllamaVisionClient:
    return _OllamaVisionClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_vision_model,
    )


def describe_image(image_bytes: bytes) -> str:
    """Returns a description string, or '' on any failure."""
    if not settings.vision_enabled:
        return ""
    try:
        return get_vision_client().describe(image_bytes)
    except VisionError as exc:
        logger.warning("vision_failed", extra={"error": str(exc)})
        return ""