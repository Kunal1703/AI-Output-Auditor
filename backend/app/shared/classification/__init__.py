"""Classification & Weighting — the shared labelling component (Document 2, §5.2).

    *Assignment of type and/or importance labels to extracted units.*

A subpackage mirroring ``extraction`` because Document 2 §5 catalogs this as
**one** shared component with several instantiations. Grouping them keeps the
shared machinery (:mod:`base`) in one place and makes each instantiation a
prompt, a schema, and a label applier.

| Instantiation | Engine stage | Status |
|---|---|---|
| Hard / Soft Requirement Classification | Relevance, stage 3 | **Milestone 3** |
| Claim Classification | Accuracy, stage 3 | **Milestone 3** |
| Claim Centrality & Severity | Accuracy, stage 4 | **Milestone 3** |
| Salience Assignment | Coverage, stage 3 | **Milestone 3** |
| Category & Severity Assignment | Coverage, stage 4 | **Milestone 3** |
| Source Classification | Credibility, stage 7 | **Milestone 3** |
| Issue Classification & Severity | Readability, stages 4–5 | Milestone 4 |
| Applicability & Stance Contract | Diversity, stages 2 & 4 | Milestone 4 |

**Classification is where labels acquire consequences.** A *Hard* requirement's
violation becomes a Critical Finding that gates trust; an *Opinion* claim is
excluded from verification entirely; a high *severity* omission is what turns a
missing sentence into an *Untrusted* verdict. That is why Document 2 keeps this
separate from extraction and gives each instantiation its own frozen stage —
and why nothing here guesses a default when the model declines to answer.
"""

from app.shared.classification.base import (
    ClassificationError,
    LLMClassifier,
    coerce_enum,
    coerce_unit_float,
    render_units,
)
from app.shared.classification.claims import ClaimCentralityAssigner, ClaimClassifier
from app.shared.classification.key_points import (
    CategorySeverityAssigner,
    SalienceAssigner,
)
from app.shared.classification.requirements import RequirementClassifier
from app.shared.classification.sources import SourceClassifier, domain_of

__all__ = [
    "CategorySeverityAssigner",
    "ClaimCentralityAssigner",
    "ClaimClassifier",
    "ClassificationError",
    "LLMClassifier",
    "RequirementClassifier",
    "SalienceAssigner",
    "SourceClassifier",
    "coerce_enum",
    "coerce_unit_float",
    "domain_of",
    "render_units",
]
