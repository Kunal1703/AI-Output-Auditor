"""Prompt Manager — loads and renders versioned prompt templates.

Document 4 §4: "Loads and renders versioned prompt templates from
``config/prompts/``", consumed by every engine stage that calls the LLM Service.
Document 1 §11 and Document 4 §15 make prompts configuration rather than code.

**Why versioning is in the filename rather than implicit.** An engine's verdicts
change when its prompt changes. Pinning ``("accuracy", "claim_extraction",
"v1")`` at the call site means a prompt revision is a deliberate, reviewable act
— you add ``claim_extraction.v2.md`` and change one line — rather than a silent
shift in what the auditor concludes. Document 4 §11 asks for results that are
stable across re-runs; an unversioned prompt file makes that promise unkeepable.

**Why ``string.Template`` and not ``str.format``.** Prompt text is full of
literal braces — JSON examples, schema snippets, the very structures these
prompts ask models to emit. ``format`` would choke on every one of them, and
escaping them all would make the templates unreadable for the humans who tune
them.

**Strict rendering is on by default and should stay on.** ``safe_substitute``
would leave a literal ``${claim}`` in the prompt and the model would answer
*something* — a confident verdict derived from a broken prompt. Failing loudly
lets the engine degrade honestly instead (Document 4, §12).
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from app.core.config import Settings
from app.core.errors import PromptNotFoundError
from app.core.logging import bind, get_logger

__all__ = ["PromptManager", "FilePromptManager", "PromptTemplate", "PROMPT_ENGINES"]

logger = get_logger(__name__)

#: The eight engine directories under ``config/prompts/``. Fixed: the dimension
#: set is closed (Document 4, §14), so a prompt directory outside this set is a
#: typo rather than an extension.
PROMPT_ENGINES: tuple[str, ...] = (
    "relevance",
    "accuracy",
    "coverage",
    "credibility",
    "novelty",
    "readability",
    "engagement",
    "diversity",
)

#: ``<stage>.<version>.md`` — the only filename shape the manager recognizes.
_TEMPLATE_FILENAME = re.compile(r"^(?P<stage>[a-z0-9_]+)\.(?P<version>v\d+)\.md$")

#: ``${name}`` and ``$name`` placeholders, per ``string.Template``.
_PLACEHOLDER = re.compile(r"\$(?:\{(?P<braced>\w+)\}|(?P<bare>\w+))")


@dataclass(frozen=True)
class PromptTemplate:
    """One discovered prompt template.

    Attributes:
        engine: Engine directory, e.g. ``"accuracy"``.
        stage: Template name, e.g. ``"claim_extraction"``.
        version: Version tag, e.g. ``"v1"``.
        path: Absolute path to the file.
        variables: Placeholder names the template requires.
    """

    engine: str
    stage: str
    version: str
    path: Path
    variables: frozenset[str]

    @property
    def identifier(self) -> str:
        """``engine/stage.version`` — how the template is referred to in logs."""
        return f"{self.engine}/{self.stage}.{self.version}"


class PromptManager(abc.ABC):
    """The interface engine stages use to obtain prompt text."""

    @abc.abstractmethod
    def render(
        self, engine: str, stage: str, variables: dict[str, Any], version: str = "v1"
    ) -> str:
        """Load a template and render it with ``variables``.

        Args:
            engine: Engine directory, e.g. ``"accuracy"``.
            stage: Template basename, e.g. ``"claim_extraction"``.
            variables: Values for the template's ``${name}`` placeholders.
            version: Template version, e.g. ``"v1"``.

        Returns:
            The rendered prompt.

        Raises:
            PromptNotFoundError: The template does not exist, or a placeholder
                had no value and strict rendering is on.
        """

    @abc.abstractmethod
    def get(self, engine: str, stage: str, version: str = "v1") -> PromptTemplate:
        """Return a template's descriptor without rendering it.

        Raises:
            PromptNotFoundError: The template does not exist.
        """

    @abc.abstractmethod
    def available(self) -> list[str]:
        """List discovered template identifiers as ``engine/stage.version``."""

    @abc.abstractmethod
    def exists(self, engine: str, stage: str, version: str = "v1") -> bool:
        """Whether a template exists, without raising."""


class FilePromptManager(PromptManager):
    """Loads templates from ``config/prompts/<engine>/<stage>.<version>.md``.

    Args:
        settings: Supplies the prompt directory and the strict-rendering flag.

    Note:
        Templates are cached after first read. The auditor runs eight engines
        over one input and would otherwise re-read the same file repeatedly.
        Restart the backend after editing a template.
    """

    def __init__(self, settings: Settings) -> None:
        self._root: Path = settings.prompts_directory
        self._strict: bool = settings.prompts.strict_rendering
        self._cache: dict[Path, tuple[Template, frozenset[str]]] = {}

    def _path(self, engine: str, stage: str, version: str) -> Path:
        return self._root / engine / f"{stage}.{version}.md"

    @staticmethod
    def _variables_of(text: str) -> frozenset[str]:
        """Return the placeholder names a template body requires."""
        return frozenset(
            match.group("braced") or match.group("bare")
            for match in _PLACEHOLDER.finditer(text)
        )

    def _load(self, path: Path, identifier: str) -> tuple[Template, frozenset[str]]:
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        if not path.is_file():
            raise PromptNotFoundError(
                f"Prompt template not found: {identifier} (expected at {path}). "
                "Templates live in config/prompts/<engine>/<stage>.<version>.md."
            )
        body = path.read_text(encoding="utf-8")
        entry = (Template(body), self._variables_of(body))
        self._cache[path] = entry
        return entry

    def get(self, engine: str, stage: str, version: str = "v1") -> PromptTemplate:
        """Return a template's descriptor without rendering it.

        Useful for validating wiring at startup — an engine can confirm its
        prompt exists before an audit depends on it.

        Raises:
            PromptNotFoundError: The template does not exist.
        """
        path = self._path(engine, stage, version)
        identifier = f"{engine}/{stage}.{version}"
        _, variables = self._load(path, identifier)
        return PromptTemplate(
            engine=engine, stage=stage, version=version, path=path, variables=variables
        )

    def exists(self, engine: str, stage: str, version: str = "v1") -> bool:
        """Whether a template exists, without raising."""
        return self._path(engine, stage, version).is_file()

    def render(
        self, engine: str, stage: str, variables: dict[str, Any], version: str = "v1"
    ) -> str:
        """Load and render a template. See :meth:`PromptManager.render`.

        Under strict rendering, a missing placeholder raises *before* the model
        is called. The alternative — ``safe_substitute`` leaving ``${claim}`` in
        the text — produces an answer to a broken question, and the engine has no
        way to tell that happened.
        """
        path = self._path(engine, stage, version)
        identifier = f"{engine}/{stage}.{version}"
        template, required = self._load(path, identifier)

        if self._strict:
            missing = required - set(variables)
            if missing:
                raise PromptNotFoundError(
                    f"Prompt {identifier} requires variable(s) "
                    f"{sorted(missing)} but they were not supplied. "
                    f"Supplied: {sorted(variables)}."
                )

        try:
            if self._strict:
                return template.substitute(variables)
            return template.safe_substitute(variables)
        except KeyError as exc:
            raise PromptNotFoundError(
                f"Prompt {identifier} requires variable {exc} but it was not "
                "supplied."
            ) from exc
        except ValueError as exc:
            # A bare '$' that is not a placeholder — a malformed template, not a
            # caller error. Name the file so it can be fixed.
            raise PromptNotFoundError(
                f"Prompt {identifier} is malformed: {exc}. Escape a literal "
                "dollar sign as '$$'."
            ) from exc

    def discover(self) -> list[PromptTemplate]:
        """Return every discovered template, sorted by identifier.

        Files that do not match ``<stage>.<version>.md`` are skipped with a
        warning rather than an error: a stray README in a prompt directory is
        documentation, not a fault.
        """
        if not self._root.is_dir():
            logger.warning(
                "prompt directory not found", extra=bind(path=str(self._root))
            )
            return []

        found: list[PromptTemplate] = []
        for path in sorted(self._root.glob("*/*.md")):
            match = _TEMPLATE_FILENAME.match(path.name)
            if match is None:
                continue
            engine = path.parent.name
            if engine not in PROMPT_ENGINES:
                logger.warning(
                    "prompt directory is not a known engine; skipping",
                    extra=bind(directory=engine, path=str(path)),
                )
                continue
            body = path.read_text(encoding="utf-8")
            found.append(
                PromptTemplate(
                    engine=engine,
                    stage=match.group("stage"),
                    version=match.group("version"),
                    path=path,
                    variables=self._variables_of(body),
                )
            )
        return found

    def available(self) -> list[str]:
        """List discovered templates as ``engine/stage.version``.

        Returns an empty list when the directory is absent — reported by the
        service container at startup rather than raising, since a deployment
        with no prompts should fail at the first audit with a clear message, not
        at import time with an obscure one.
        """
        return [template.identifier for template in self.discover()]
