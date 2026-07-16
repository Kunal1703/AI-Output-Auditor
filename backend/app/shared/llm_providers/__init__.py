"""LLM provider abstraction.

The provider seam required by Document 4 §2: one interface, many backends,
selected by configuration. **Groq is the active provider.** OpenAI, Ollama, and
Anthropic can be added as sibling modules plus a registry entry, without
touching the audit engines.

A paid provider (OpenRouter) is already written and ships commented out in
``registry.py`` — see the ``PAID PROVIDER`` blocks there for how to enable it.
``openrouter.py`` is intentionally not exported here: it is not wired until
those blocks are uncommented.
"""

from app.shared.llm_providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
)
from app.shared.llm_providers.groq import GroqProvider
from app.shared.llm_providers.registry import (
    available_providers,
    build_provider,
    register_provider,
)

__all__ = [
    "ChatMessage",
    "CompletionRequest",
    "CompletionResponse",
    "LLMProvider",
    "GroqProvider",
    "available_providers",
    "build_provider",
    "register_provider",
]
