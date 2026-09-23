from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Interface every generation backend implements. Swapping OpenAI <->
    Anthropic <-> a local Ollama model is a config change, not a code
    change, anywhere in the orchestrator or prompt layer."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...
