"""Custom exceptions for LLM provider errors."""


class LLMError(Exception):
    """Base exception for LLM provider errors."""

    def __init__(self, message: str, provider: str = "", category: str = ""):
        super().__init__(message)
        self.provider = provider
        self.category = category


class ConfigurationError(LLMError):
    """Non-recoverable configuration error (e.g., missing API key)."""


class RecoverableLLMError(LLMError):
    """Recoverable error that may succeed with a fallback provider."""
