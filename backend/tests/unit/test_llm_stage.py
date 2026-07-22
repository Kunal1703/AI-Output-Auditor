"""LLMStage record recovery — the shapes models actually return (Document 2 §5).

`_records` turns a model's chosen container shape into the record list every
LLM-backed stage consumes. It must tolerate the honest shapes without ever
silently misreading data — an empty object is "nothing to report", but an object
with unrecognized data is an error, not an empty list.
"""

from __future__ import annotations

import pytest

from app.shared.llm_stage import LLMStage, LLMStageError

pytestmark = pytest.mark.unit


class _Stage(LLMStage):
    engine = "x"
    stage = "y"
    collection_key = "mappings"


def stage() -> _Stage:
    return _Stage.__new__(_Stage)  # no LLM/prompt needed for _records


def test_empty_object_is_no_records_not_an_error():
    """A stage with nothing to report (no citations to map) must not degrade."""
    assert stage()._records({}) == []


def test_recovers_the_named_collection():
    assert stage()._records({"mappings": [{"a": 1}]}) == [{"a": 1}]


def test_recovers_a_bare_array():
    assert stage()._records([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


def test_non_empty_object_without_a_list_still_raises():
    """Unrecognized data must fail loudly rather than be read as empty."""
    with pytest.raises(LLMStageError):
        stage()._records({"unexpected": "value"})


def test_non_dict_non_list_raises():
    with pytest.raises(LLMStageError):
        stage()._records("nonsense")
