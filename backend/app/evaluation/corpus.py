"""Validation corpus loader (Document 4, §11).

Reads the labelled samples in ``datasets/`` and hands them to the calibration
runner. Each sample is a markdown file whose YAML frontmatter carries the
prompt, the optional reference source, and the **expected** auditor behavior.

**Why expectations live with the sample.** Document 4 §11 asks for a results
table of *sample → expected class → observed verdict → pass/fail*. Keeping the
expectation next to the content means the claim and the evidence for it cannot
drift apart, and a reviewer reading one sample can see what it is supposed to
prove without cross-referencing a spreadsheet.

**Expectations are ranges, not point values.** A sample asserts "not Untrusted"
or "Trusted or Trusted with Caveats" rather than a single verdict. That is
deliberate: Document 4 §11's success criterion is that verdicts *track* quality
and that defects map to the right dimension — not that a model produces one
exact band. Pinning an exact verdict would make the corpus a change-detector for
prompt wording rather than a test of the system's claim.

This module is evaluation tooling, not part of the audit path. Nothing in
``audit_engines`` or ``decision_engine`` imports it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

from app.core.config import PROJECT_ROOT

__all__ = ["Sample", "load_corpus", "CORPUS_ROOT"]

#: Where the labelled samples live.
CORPUS_ROOT: Path = PROJECT_ROOT / "datasets"

#: ``---\n<yaml>\n---\n<body>``
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Sample:
    """One labelled corpus sample.

    Attributes:
        sample_id: Stable id from the frontmatter.
        tier: ``good`` / ``medium`` / ``poor`` — the folder it came from.
        kinds: What this sample is an example of, e.g. ``["news article",
            "citation-free"]``. Drives the coverage report.
        path: Source file.
        content: The AI Output under audit — the body after the frontmatter.
        prompt: The instruction to audit against, when the sample supplies one.
        reference: Ground-truth text, when a sibling ``.reference.md`` exists.
        expect: The expected auditor behavior. See :mod:`corpus` docstring.
        notes: Why this sample exists and what it is meant to prove.
    """

    sample_id: str
    tier: str
    kinds: tuple[str, ...]
    path: Path
    content: str
    prompt: str | None = None
    reference: str | None = None
    expect: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @property
    def label(self) -> str:
        """``tier/sample_id`` — how the sample appears in the results table."""
        return f"{self.tier}/{self.sample_id}"


def _parse(path: Path) -> Sample | None:
    """Parse one sample file, or return None if it is not one."""
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if match is None:
        return None

    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()

    reference_path = path.with_suffix("").with_suffix(".reference.md")
    if not reference_path.exists() and meta.get("reference"):
        reference_path = path.parent / str(meta["reference"])

    return Sample(
        sample_id=str(meta.get("id") or path.stem),
        tier=str(meta.get("tier") or path.parent.name),
        kinds=tuple(meta.get("kinds") or []),
        path=path,
        content=body,
        prompt=meta.get("prompt"),
        reference=(
            reference_path.read_text(encoding="utf-8")
            if reference_path.exists()
            else None
        ),
        expect=dict(meta.get("expect") or {}),
        notes=str(meta.get("notes") or "").strip(),
    )


def load_corpus(root: Path | None = None) -> list[Sample]:
    """Load every labelled sample, in a stable order.

    Args:
        root: Corpus root. Defaults to ``datasets/``.

    Returns:
        The samples, ordered good → medium → poor then by id, so the results
        table reads the way a reviewer expects and diffs cleanly between runs.
    """
    base = root or CORPUS_ROOT
    order = {"good": 0, "medium": 1, "poor": 2}
    samples: list[Sample] = []

    for path in sorted(base.glob("*/*.md")):
        if path.name.endswith(".reference.md") or path.name == "README.md":
            continue
        sample = _parse(path)
        if sample is not None:
            samples.append(sample)

    samples.sort(key=lambda s: (order.get(s.tier, 9), s.sample_id))
    return samples


def coverage(samples: list[Sample]) -> dict[str, list[str]]:
    """Map each declared kind to the samples covering it.

    Backs the corpus's own completeness check: Work 6 names eight content
    categories that must be represented, and a corpus that silently lost one
    would report a clean run over an incomplete claim.
    """
    found: dict[str, list[str]] = {}
    for sample in samples:
        for kind in sample.kinds:
            found.setdefault(kind, []).append(sample.label)
    return found


def __iter__() -> Iterator[Sample]:  # pragma: no cover - convenience only
    return iter(load_corpus())
