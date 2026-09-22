import os

from opshub.llm.base import LLMProvider
from opshub.llm.exceptions import ConfigurationError


def get_llm_provider() -> LLMProvider:
    """Factory to get LLM provider based on environment."""
    provider = os.getenv("LLM_PROVIDER", "mock")

    if provider == "mock":
        from opshub.llm.mock import MockLLMProvider

        return MockLLMProvider()
    elif provider == "qwen":
        from opshub.llm.qwen import QwenProvider

        return QwenProvider()
    elif provider == "nex":
        from opshub.llm.nex import NexProvider

        return NexProvider()
    elif provider == "fallback":
        from opshub.llm.qwen import QwenProvider
        from opshub.llm.nex import NexProvider
        from opshub.llm.fallback import FallbackLLMProvider

        return FallbackLLMProvider(
            primary=QwenProvider(),
            fallback=NexProvider(),
        )
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider}. "
            "Use 'mock', 'qwen', 'nex', or 'fallback'."
        )
