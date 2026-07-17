"""Evaluation tooling — the validation corpus and the calibration runner.

Document 4 §11 defines the validation strategy this package implements: run the
auditor over labelled samples and prove it **separates good content from bad**.

**This package is not part of the audit path.** Nothing in ``audit_engines`` or
``decision_engine`` imports it, and it may read anything it likes without
disturbing the one-way dependency graph of Document 1 §6. It is a consumer of
the system, in the same position as the API.
"""

from __future__ import annotations

from app.evaluation.corpus import CORPUS_ROOT, Sample, load_corpus

__all__ = ["CORPUS_ROOT", "Sample", "load_corpus"]
