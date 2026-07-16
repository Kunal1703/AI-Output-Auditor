"""The machinery shared by every LLM-backed pipeline stage.

Document 2 §5 catalogs three LLM-backed shared components, and all three do the
same four mechanical things before they do anything interesting:

* **§5.1 LLM Extraction** — decompose an input into units.
* **§5.2 Classification & Weighting** — attach type and importance labels.
* **§5.4 LLM Verification / Judge** — render a per-unit verdict against evidence.

The four things: render a versioned prompt, call the LLM Service, recover a list
of records from a response whose container shape the model chose, and refuse to
carry on if any of that failed. Written once here so that adding Coverage's
Salience Assignment or Credibility's Grounding Verification is a prompt, a
schema, and a record mapper — not a fourth copy of JSON-shape tolerance.

**This class knows nothing about auditing.** It has no opinion about claims,
requirements, or verdicts. Everything above it — what to extract, what to label,
what a verdict means — belongs to the component that extends it and, ultimately,
to the engine stage that calls it.
"""

from __future__ import annotations

import abc
from typing import Any, Sequence

from app.core.errors import ProviderError
from app.core.logging import bind, get_logger
from app.shared.llm_providers.base import ChatMessage
from app.shared.llm_service import LLMService
from app.shared.prompt_manager import PromptManager

__all__ = ["LLMStage", "LLMStageError"]

logger = get_logger(__name__)


class LLMStageError(ProviderError):
    """An LLM-backed stage could not produce a usable result.

    Subclasses :class:`~app.core.errors.ProviderError` so an engine's existing
    provider-failure handling covers it: the engine catches, degrades, and the
    Decision Engine reads the gap (Document 4, §12). A stage never decides what
    its own failure means for the dimension — only the engine has the context
    to know whether a failed sub-stage is fatal or survivable.
    """

    code = "llm_stage_failed"


class LLMStage(abc.ABC):
    """Base for any pipeline stage that calls an LLM through a versioned prompt.

    Args:
        llm: The Shared LLM Service. Injected — an engine never reaches a
            provider directly (Document 4, §4), and neither does this. All
            provider specifics (Groq's JSON mode, its reasoning-format quirk)
            live behind it, which is what keeps engines provider-independent.
        prompts: The Prompt Manager. Prompts are configuration, not code
            (Document 4, §15), so nothing in any subclass contains prompt text.

    Attributes:
        engine: Prompt directory, e.g. ``"accuracy"``.
        stage: Prompt template name, e.g. ``"claim_verification"``.
        version: Prompt version, pinned per stage. A prompt revision changes
            what the auditor concludes, so it must be a deliberate edit to a
            pinned version rather than a silent in-place rewrite.
        collection_key: The key the prompt asks the model to wrap its list in.
        error_class: The exception this stage raises on failure. Subclasses
            narrow it — extraction raises ``ExtractionError`` — so a caller can
            catch the specific failure its docstring promises rather than having
            to know that a base class sits underneath.
    """

    engine: str = ""
    stage: str = ""
    version: str = "v1"
    collection_key: str = "items"
    error_class: type[LLMStageError] = LLMStageError

    def __init__(self, llm: LLMService, prompts: PromptManager) -> None:
        if not self.engine or not self.stage:
            raise TypeError(
                f"{type(self).__name__} must declare 'engine' and 'stage' so its "
                "prompt can be resolved."
            )
        self._llm = llm
        self._prompts = prompts

    @property
    def identifier(self) -> str:
        """``engine/stage.version`` — how this stage appears in logs."""
        return f"{self.engine}/{self.stage}.{self.version}"

    async def _invoke(
        self, variables: dict[str, Any], schema: dict[str, Any] | None = None
    ) -> Any:
        """Render this stage's prompt and call the model.

        Args:
            variables: Values for the template's placeholders.
            schema: JSON Schema for the response, passed to the LLM Service.

        Returns:
            The parsed JSON payload.

        Raises:
            LLMStageError: The prompt could not be rendered, or the provider
                failed after the LLM Service exhausted its retries.
        """
        try:
            rendered = self._prompts.render(
                engine=self.engine,
                stage=self.stage,
                variables=variables,
                version=self.version,
            )
        except Exception as exc:
            raise self.error_class(
                f"Could not render prompt {self.identifier}: {exc}"
            ) from exc

        try:
            return await self._llm.complete_json(
                [ChatMessage(role="user", content=rendered)], json_schema=schema
            )
        except ProviderError as exc:
            raise self.error_class(f"{self.identifier} failed: {exc.message}") from exc

    def _records(self, payload: Any, key: str | None = None) -> list[dict[str, Any]]:
        """Recover the record list from the model's response.

        Tolerates the shapes models actually return — a bare array, or an object
        wrapping one under the asked-for key, a common synonym, or the only list
        present. Failing an audit over a container shape would be a poor trade
        when the intent is unambiguous; the *contents* still get validated by the
        caller.

        Args:
            payload: The parsed response.
            key: Expected collection key. Defaults to :attr:`collection_key`.

        Returns:
            The records, with non-object entries dropped.

        Raises:
            LLMStageError: No recognizable list is present.
        """
        wanted = key or self.collection_key

        if isinstance(payload, list):
            candidate: list[Any] = payload
        elif isinstance(payload, dict):
            for name in (wanted, "items", "results", "units", "verdicts"):
                value = payload.get(name)
                if isinstance(value, list):
                    candidate = value
                    break
            else:
                lists = [v for v in payload.values() if isinstance(v, list)]
                if len(lists) != 1:
                    raise self.error_class(
                        f"{self.identifier} returned an object with no "
                        f"unambiguous list (keys: {sorted(payload)})."
                    )
                candidate = lists[0]
        else:
            raise self.error_class(
                f"{self.identifier} returned {type(payload).__name__}, expected a "
                "list or an object containing one."
            )

        return [record for record in candidate if isinstance(record, dict)]

    async def _run_records(
        self,
        variables: dict[str, Any],
        schema: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Invoke the stage and recover its records in one step."""
        payload = await self._invoke(variables, schema)
        records = self._records(payload, key)
        logger.debug(
            "llm stage returned records",
            extra=bind(stage=self.identifier, records=len(records)),
        )
        return records


def index_by(records: Sequence[dict[str, Any]], id_key: str) -> dict[str, dict[str, Any]]:
    """Index records by an id field, ignoring any that lack one.

    Classification and verification stages send the model a numbered list of
    units and get back a list of judgments. Matching them **by id, never by
    position**, is deliberate: a model that drops or reorders one entry would,
    under positional matching, silently attach every subsequent verdict to the
    wrong unit — labelling an innocuous claim *Contradicted* and a hallucinated
    one *Supported*. That failure is invisible in the output and catastrophic in
    the report, so id matching is the only safe option and the caller is
    expected to treat an unmatched unit as unjudged.

    Args:
        records: Records from the model.
        id_key: The field holding the unit id.

    Returns:
        Records keyed by id. Later duplicates overwrite earlier ones.
    """
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record.get(id_key)
        if isinstance(identifier, str) and identifier.strip():
            indexed[identifier.strip()] = record
    return indexed
