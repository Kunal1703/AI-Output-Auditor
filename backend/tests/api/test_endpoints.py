"""API surface (Document 4, §7).

The API is thin by mandate — it accepts requests, tracks async jobs, and returns
the report. These tests hold the *contracts*: the error shape, the job
lifecycle, the status contract, and the report shape. They do not assert
verdicts, because the API does not decide them (Document 4, §5).

No API key is needed. Without one every engine degrades and the report comes
back *Unable to Verify* — which is exactly the fail-safe path worth asserting.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.api

SAMPLE = (
    "Rate limiting caps how many requests a client may make in a window of time. "
    "The token bucket refills at a fixed rate and each request costs one token."
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def wait_for(client, audit_id: str, timeout: float = 240.0) -> dict:
    """Poll a job to a terminal state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/audit/{audit_id}/status").json()
        if status["status"] in ("completed", "failed"):
            return status
        time.sleep(0.4)
    raise AssertionError(f"{audit_id} did not finish within {timeout}s")


def test_health_reports_readiness(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["engines_registered"] == 8      # all eight registered at startup
    assert body["prompt_templates"] == 27
    assert body["llm_provider"] == "groq"
    # Reported honestly rather than assumed — a deployment with no key should be
    # visible on /health, not discovered at the first audit.
    assert isinstance(body["llm_configured"], bool)


def test_error_contract_is_frozen(client):
    """Document 4 §7: { "error": { "code", "message" } }."""
    response = client.get("/report/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_async_job_lifecycle_and_real_progress(client):
    created = client.post("/audit/text", json={"text": SAMPLE, "prompt": "Explain."})
    assert created.status_code == 202
    audit_id = created.json()["audit_id"]
    assert created.json()["status"] in ("queued", "processing")

    status = wait_for(client, audit_id)
    assert status["status"] == "completed"
    # Progress is real: it comes from the orchestrator's own callback.
    assert status["engines_completed"] == status["engines_total"] == 8


def test_report_shape_is_the_frozen_contract(client):
    created = client.post("/audit/text", json={"text": SAMPLE, "prompt": "Explain."})
    audit_id = created.json()["audit_id"]
    wait_for(client, audit_id)

    body = client.get(f"/report/{audit_id}").json()

    assert body["audit_id"] == audit_id
    assert body["overall_verdict"] in {
        "Trusted", "Trusted with Caveats", "Needs Revision",
        "Untrusted", "Unable to Verify",
    }
    # Two axes, always separate, never fused (Document 3, §7).
    assert body["trust_verdict"]["verdict"]
    assert body["trust_verdict"]["reason"]
    assert body["quality_verdict"]["band"]
    assert len(body["dimension_results"]) == 8
    assert len(body["dimension_summaries"]) == 8
    assert all(row["rationale"] for row in body["dimension_summaries"])
    assert len(body["confidence"]["per_dimension"]) == 8
    assert body["summary"]


def test_evidence_is_traceable_in_the_report(client):
    created = client.post("/audit/text", json={"text": SAMPLE})
    audit_id = created.json()["audit_id"]
    wait_for(client, audit_id)
    body = client.get(f"/report/{audit_id}").json()

    known = {
        item["evidence_id"]
        for result in body["dimension_results"]
        for item in result["evidence"]
    }
    for holder in (*body["critical_findings"], *body["recommendations"]):
        assert holder["evidence_refs"], "emitted without evidence"
        assert set(holder["evidence_refs"]) <= known, "dangling reference"


def test_unknown_status_id_is_a_clean_404(client):
    response = client.get("/audit/nope/status")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "payload",
    [{}, {"text": ""}, {"text": SAMPLE, "url": "https://example.org"}],
    ids=["empty", "blank-text", "both-text-and-url"],
)
def test_invalid_requests_are_rejected(client, payload):
    response = client.post("/audit", json=payload)
    assert response.status_code >= 400
    assert "error" in response.json()


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t "], ids=["empty", "spaces", "newlines"])
def test_whitespace_only_text_is_rejected(client, text):
    """`min_length=1` admits `"   "`, which strips to an audit of nothing."""
    response = client.post("/audit/text", json={"text": text})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_file_upload_rejects_an_unsupported_format(client):
    response = client.post(
        "/audit/file",
        files={"file": ("virus.exe", b"MZ" + b"x" * 400, "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_input"


def test_file_upload_accepts_markdown(client):
    response = client.post(
        "/audit/file",
        files={"file": ("notes.md", ("# Notes\n\n" + SAMPLE).encode(), "text/markdown")},
        data={"prompt": "Explain rate limiting."},
    )
    assert response.status_code == 202
    status = wait_for(client, response.json()["audit_id"])
    assert status["status"] == "completed"
