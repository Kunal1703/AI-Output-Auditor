"""Context & Task Identification — Engagement's stage 2.

Document 2 §7.7 opens the Engagement pipeline with *"Context & Task
Identification"*, before the reuse stage and before any judgment. This module is
that stage.

**Why it is its own stage and not part of the fitness judge.** Engagement's
question is whether the content *helps the user achieve their goal* — and a goal
is not a given, it is an inference from the prompt. "Write me something about
rate limiting for our new backend engineers" implies an audience, a purpose, and
a bar for success that no generic rubric contains. Naming those first, explicitly
and inspectably, means stage 4 evaluates against criteria a reader can argue with
rather than against a standard the model kept to itself.

**It extends :class:`~app.shared.llm_stage.LLMStage` directly**, unlike the
extraction, classification, and verification components. Those three answer
"one record per unit"; this stage answers with a single object describing one
task. §5 catalogues the components each engine uses and Engagement's list names
the Shared LLM Service, which is what this is — the base class exists for
precisely "any pipeline stage that calls an LLM through a versioned prompt".

**Without a prompt there is no task.** The Engine Input Contract makes the prompt
optional (§6.1), and Engagement is one of the three engines that needs it. When
it is absent this stage returns ``identified=False`` rather than inventing a goal
from the output itself — an output judged against a goal inferred from that same
output would grade its own homework, and would pass every time.
"""

from __future__ import annotations

import itertools
from typing import Any

from app.core.logging import bind, get_logger
from app.shared.llm_stage import LLMStage, LLMStageError
from app.shared.quality_units import TaskContext, TaskCriterion

__all__ = ["TaskIdentificationStage", "TaskIdentificationError"]

logger = get_logger(__name__)


class TaskIdentificationError(LLMStageError):
    """The task-identification stage could not describe the user's task."""

    code = "task_identification_failed"


class TaskIdentificationStage(LLMStage):
    """Stage 2 — identifies the user's task, goal, audience, and success criteria.

    Args:
        llm: The Shared LLM Service.
        prompts: The Prompt Manager.
    """

    engine = "engagement"
    stage = "task_identification"
    version = "v1"
    collection_key = "criteria"
    error_class: type[LLMStageError] = TaskIdentificationError

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "The kind of request, e.g. summarization, "
                    "explanation, comparison, recommendation, troubleshooting.",
                },
                "goal": {
                    "type": "string",
                    "description": "What the user is trying to accomplish, in "
                    "one sentence.",
                },
                "audience": {
                    "type": "string",
                    "description": "Who the output is for, as far as the prompt "
                    "reveals. Say 'unstated' when it does not.",
                },
                "criteria": {
                    "type": "array",
                    "description": "What the output must do to serve the goal.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {
                                "type": "string",
                                "description": "One thing the output must do, "
                                "stated so it can be checked.",
                            },
                            "importance": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "How much this matters to the "
                                "user's goal.",
                            },
                        },
                        "required": ["criterion", "importance"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["task_type", "goal", "criteria"],
            "additionalProperties": False,
        }

    async def identify(self, prompt: str, ai_output: str) -> TaskContext:
        """Identify the task the user set.

        Args:
            prompt: The user's original instruction.
            ai_output: The content under audit. Supplied for *context only* —
                the criteria must come from what was asked, and the prompt says
                so in as many words. An output visible to this stage will
                otherwise pull the criteria toward what it happens to contain,
                which is how an engine ends up certifying that the answer
                answers itself.

        Returns:
            The identified task. ``identified=False`` when no prompt was
            supplied — the honest answer, and the one that makes Engagement
            report low confidence rather than measure against an invention.

        Raises:
            TaskIdentificationError: The prompt could not be rendered, the
                provider failed, or the response could not be parsed.
        """
        if not prompt or not prompt.strip():
            return TaskContext(
                task_type="unknown",
                goal="No prompt was supplied, so the user's goal is unknown.",
                audience="unknown",
                criteria=(),
                identified=False,
            )

        payload = await self._invoke(
            {"prompt": prompt, "ai_output": ai_output}, self._response_schema()
        )
        if not isinstance(payload, dict):
            raise self.error_class(
                f"{self.identifier} returned {type(payload).__name__}, expected "
                "an object describing the task."
            )

        ids = itertools.count(1)
        criteria: list[TaskCriterion] = []
        for record in payload.get("criteria") or []:
            if not isinstance(record, dict):
                continue
            text = record.get("criterion")
            if not isinstance(text, str) or not text.strip():
                continue
            importance = record.get("importance")
            criteria.append(
                TaskCriterion(
                    criterion_id=f"crt_{next(ids)}",
                    text=text.strip(),
                    importance=(
                        min(1.0, max(0.0, float(importance)))
                        if isinstance(importance, (int, float))
                        and not isinstance(importance, bool)
                        else 0.5
                    ),
                )
            )

        context = TaskContext(
            task_type=str(payload.get("task_type") or "unknown").strip(),
            goal=str(payload.get("goal") or "").strip(),
            audience=str(payload.get("audience") or "unstated").strip(),
            criteria=tuple(criteria),
            identified=bool(criteria),
        )
        logger.info(
            "task identified",
            extra=bind(
                stage=self.identifier,
                task_type=context.task_type,
                criteria=len(criteria),
            ),
        )
        return context
