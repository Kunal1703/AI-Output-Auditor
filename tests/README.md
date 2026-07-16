# Tests

Test levels per Document 4 §10. Each level verifies a distinct guarantee.

| Level | Location | Verifies |
|---|---|---|
| **Unit** | `unit/` | Shared Services in isolation: LLM retry/timeout handling, embedding similarity, retrieval chunking, validator correctness, prompt rendering, schema validation. LLM mocked. |
| **Engines** | `engines/` | Each engine returns a schema-valid `AuditResult`; ledgers, evidence links, confidence, and critical findings appear correctly. Fixed fixtures, mocked LLM. |
| **Decision** | `decision/` | Document 3 rules: a qualifying critical finding forces **Untrusted**; low trust-confidence yields **Unable to Verify**; N/A excluded fairly; verdict resolution order; recommendation prioritization; trust/quality separation. |
| **API** | `api/` | Endpoints accept valid contracts, reject invalid ones, create jobs, report status, return a schema-valid report. |
| **Integration** | (root) | Orchestrator honors cross-engine ordering and produces a complete report from one input. |
| **E2E** | `e2e/` | Full text and URL runs against the live stack: input → report → expected verdict class. |

## Rules

Mock the LLM and network in unit and engine tests for determinism and speed;
reserve real provider calls for a small E2E set.

**The Decision Engine suite must be exhaustive on gate logic.** It is the
correctness core, and it is cheap to test because it is fully deterministic
given its inputs — only the engines carry model variability.

## Running

```bash
cd backend
pip install -r requirements.txt -r requirements-m2.txt   # brings in pytest
pytest ../tests
```

## Status

Empty in Milestone 1. The suites are written in Milestone 2 alongside the
engines and decision workflow they exercise.
