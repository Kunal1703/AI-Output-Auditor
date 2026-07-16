"""Preprocessing — turns raw input into the context the engines expect.

Document 4 §3 and §5. Accepts text, URL, or file; extracts and normalizes it
into a ``SharedContext`` that wraps a ``PreprocessedContent`` carrying the
Engine Input Contract of Document 2 §6.1, and adds the run-scoped store engines
use to share derived work.

It normalizes. It does not evaluate — that is the engines' job, and the boundary
is what keeps the audit describing the text the user actually submitted.
"""

from app.preprocessing.content_extractor import (
    ContentExtractor,
    DefaultContentExtractor,
    ExtractedContent,
)
from app.preprocessing.input_router import DefaultInputRouter, InputRouter

__all__ = [
    "ContentExtractor",
    "DefaultContentExtractor",
    "DefaultInputRouter",
    "ExtractedContent",
    "InputRouter",
]
