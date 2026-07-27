"""AI Output Auditor — backend application package.

Audits one or more outputs (human- or LLM-written summaries/answers) against a
source article and returns an evidence-backed comparative report.

* ``core`` — configuration, logging, errors, and the metric/layer matrix.
* ``shared`` — the shared services (LLM, embeddings, NLI, retrieval, evidence,
  extraction) and the contract schemas.
* ``attribution`` — the retrieve-then-entail grounding substrate.
* ``evaluators`` — the metric evaluators (Faithfulness, Numeric Accuracy,
  Coverage, Meaning Preservation, Readability, Conciseness, Bias).
* ``orchestration`` — the Audit Orchestrator, layered Decision Engine, and report
  assembly.
* ``preprocessing`` — text / URL normalization into audit contexts.
* ``api`` — the FastAPI surface.
* ``app`` — the service container that wires it all together.

The dependency graph is one-way: Configuration → Shared Services → Attribution →
Evaluators → Decision → Assembly → API. Nothing lower imports something higher.
"""

__version__ = "1.0.0"
