"""LLM Verification / Judge — the shared per-unit verdict component (§5.4).

    *LLM-based rendering of a per-unit verdict against evidence or criteria.*

A subpackage mirroring ``extraction`` and ``classification``, because Document 2
§5 catalogs this as **one** shared component with several instantiations.

| Instantiation | Vocabulary (§6.4) | Engine stage | Status |
|---|---|---|---|
| Claim Verification | Supported / Contradicted / Unverifiable | Accuracy, stage 6 | **Milestone 3** |
| Coverage Verification | Present / Partial / Absent | Coverage, stage 5 | **Milestone 3** |
| Grounding Verification | Supports / Partial / Contradicts / Unrelated | Credibility, stage 6 | **Milestone 3** |
| Per-Requirement Evaluation | *(not frozen — see vocabularies)* | Relevance, stage 4 | **Milestone 3** |
| Functional Repetition Review | — | Novelty, stage 6 | Milestone 4 |
| Readability Review | — | Readability, stage 3 | Milestone 4 |
| Task Fitness / Manipulation | — | Engagement, stages 4 & 6 | Milestone 4 |
| Balance / Bias Detection | — | Diversity, stages 7–8 | Milestone 4 |

**This is where the auditor's judgment happens**, and the base class holds it to
three rules: a verdict must carry a rationale (Document 3 §13 — the rationale
*is* the support for an LLM judgment); a judge may return only its frozen
vocabulary; and a unit the model skipped stays unjudged rather than defaulted.

The last one matters most. Verdicts match units by **id, never position** — a
model that drops one entry would, under positional matching, shift every
subsequent verdict onto the wrong unit and mark a hallucinated claim
*Supported*, with nothing in the output to reveal it.
"""

from app.shared.verification.base import Judgment, LLMJudge, VerificationError
from app.shared.verification.claims import ClaimVerificationJudge
from app.shared.verification.coverage import CoverageVerificationJudge
from app.shared.verification.grounding import GroundingVerificationJudge
from app.shared.verification.requirements import RequirementEvaluationJudge

__all__ = [
    "ClaimVerificationJudge",
    "CoverageVerificationJudge",
    "GroundingVerificationJudge",
    "Judgment",
    "LLMJudge",
    "RequirementEvaluationJudge",
    "VerificationError",
]
