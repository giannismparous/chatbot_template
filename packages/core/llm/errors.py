from __future__ import annotations


class LLMError(Exception):
    """Base class for classified LLM transport errors."""


class LLMRateLimitError(LLMError):
    pass


class LLMQuotaError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMServerError(LLMError):
    pass


class LLMClientError(LLMError):
    pass
