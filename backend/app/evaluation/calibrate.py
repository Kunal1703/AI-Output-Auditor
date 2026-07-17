"""Calibration runner — proves the auditor separates good content from bad.

Document 4 §11's validation strategy, executable::

    cd backend
    python -m app.evaluation.calibrate            # needs GROQ_API_KEY
    python -m app.evaluation.calibrate --json out.json

Runs every labelled sample through the **real** stack — the real orchestrator,
the real Decision Engine, the real provider — and prints the results table §11
asks for: *sample → expected class → observed verdict → pass/fail*.

**This tool asserts nothing about how the auditor should work.** It reads the
expectations the samples declare and reports what happened. When a row fails,
the fix is either the system or the expectation, and deciding which is a human
judgment — so the runner prints the evidence and stops there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.app import ServiceContainer, build_container
from app.core.constants import ALL_DIMENSIONS
from app.evaluation.corpus import Sample, coverage, load_corpus
from app.shared.schemas import AuditReport

__all__ = ["Outcome", "run_sample", "run_corpus", "main"]

#: The eight content categories Work 6 requires the corpus to represent. A
#: corpus missing one would report a clean run over an incomplete claim.
REQUIRED_KINDS: tuple[str, ...] = (
    "high-quality trustworthy",
    "low-quality",
    "opinion piece",
    "news article",
    "technical documentation",
    "AI-generated text",
    "citation-heavy",
    "citation-free",
)


@dataclass
class Outcome:
    """One sample's result.

    Attributes:
        sample: The sample that ran.
        report: The Final Audit Report, or None when the run itself failed.
        failures: Expectation violations, empty when the sample passed.
        elapsed: Wall-clock seconds.
        error: The exception message, when the run failed outright.
    """

    sample: Sample
    report: AuditReport | None
    failures: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> bool:
        """Whether the observed behavior matched every declared expectation."""
        return self.report is not None and not self.failures

    @property
    def observed(self) -> str:
        """The observed verdict, for the results table."""
        if self.report is None:
            return f"ERROR: {self.error}"
        return self.report.overall_verdict.value


def _check(sample: Sample, report: AuditReport) -> list[str]:
    """Compare a report against the sample's declared expectations.

    Every key is optional — a sample asserts only what it is meant to prove, so
    a Diversity sample says nothing about Readability and does not accidentally
    pin it.
    """
    expect = sample.expect
    problems: list[str] = []
    overall = report.overall_verdict.value
    trust = report.trust_verdict.verdict.value

    if "overall" in expect and overall not in expect["overall"]:
        problems.append(f"overall {overall!r} not in {expect['overall']}")
    if "overall_not" in expect and overall in expect["overall_not"]:
        problems.append(f"overall {overall!r} is excluded by overall_not")
    if "trust" in expect and trust not in expect["trust"]:
        problems.append(f"trust {trust!r} not in {expect['trust']}")
    if "trust_not" in expect and trust in expect["trust_not"]:
        problems.append(f"trust {trust!r} is excluded by trust_not")
    if "quality" in expect and report.quality_verdict.band.value not in expect["quality"]:
        problems.append(
            f"quality {report.quality_verdict.band.value!r} not in {expect['quality']}"
        )

    findings = report.critical_findings
    if "critical_findings" in expect and len(findings) != expect["critical_findings"]:
        problems.append(
            f"expected exactly {expect['critical_findings']} critical finding(s), "
            f"got {len(findings)} ({[f.type for f in findings]})"
        )
    if "critical_findings_min" in expect and len(findings) < expect["critical_findings_min"]:
        problems.append(
            f"expected >= {expect['critical_findings_min']} critical finding(s), "
            f"got {len(findings)}"
        )
    if "finding_dimension" in expect:
        dimensions = {f.dimension for f in findings}
        if expect["finding_dimension"] not in dimensions:
            problems.append(
                f"expected a {expect['finding_dimension']} critical finding; "
                f"findings came from {sorted(dimensions) or 'nothing'}"
            )

    by_dimension = {r.metadata.dimension: r for r in report.dimension_results}

    if "diversity_applicable" in expect:
        diversity = by_dimension.get("Diversity")
        actual = bool(diversity and diversity.metadata.applicable)
        if actual != bool(expect["diversity_applicable"]):
            problems.append(
                f"expected Diversity applicable={expect['diversity_applicable']}, "
                f"got {actual}"
            )
    if "diversity_max_score" in expect:
        diversity = by_dimension.get("Diversity")
        score = diversity.score if diversity else None
        if isinstance(score, float) and score > expect["diversity_max_score"]:
            problems.append(
                f"expected Diversity <= {expect['diversity_max_score']}, got {score:.2f}"
            )
    if "low_confidence_expected" in expect and expect["low_confidence_expected"]:
        if not report.confidence.low_confidence_dimensions:
            problems.append(
                "expected low-confidence dimensions, but every dimension was "
                "measured confidently"
            )
    if "engagement_manipulation_min" in expect:
        engagement = by_dimension.get("Engagement")
        items = [
            e for e in (engagement.ledger if engagement else [])
            if e.unit_type == "Manipulation item"
        ]
        if len(items) < expect["engagement_manipulation_min"]:
            problems.append(
                f"expected >= {expect['engagement_manipulation_min']} manipulation "
                f"items, got {len(items)}"
            )
    if "engagement_manipulation_confirmed" in expect:
        engagement = by_dimension.get("Engagement")
        confirmed = [
            e for e in (engagement.ledger if engagement else [])
            if e.unit_type == "Manipulation item" and e.verdict == "Manipulative"
        ]
        if len(confirmed) != expect["engagement_manipulation_confirmed"]:
            problems.append(
                f"expected {expect['engagement_manipulation_confirmed']} CONFIRMED "
                f"manipulation item(s), got {len(confirmed)} — the verification "
                "stage may be over-confirming the regex"
            )

    # Invariants every sample must hold, declared or not. These are the
    # system's promises, and a corpus run is the last place they could break.
    known = {e.evidence_id for r in report.dimension_results for e in r.evidence}
    for finding in findings:
        if not finding.evidence_refs:
            problems.append(f"finding {finding.finding_id} carries no evidence")
        for ref in finding.evidence_refs:
            if ref not in known:
                problems.append(f"finding {finding.finding_id} has dangling ref {ref}")
    for rec in report.recommendations:
        if not rec.evidence_refs:
            problems.append(f"recommendation from {rec.dimension} carries no evidence")
        for ref in rec.evidence_refs:
            if ref not in known:
                problems.append(f"recommendation ref {ref} is dangling")
    for dimension in ALL_DIMENSIONS:
        result = by_dimension.get(dimension)
        if result is None:
            problems.append(f"{dimension} produced no result")
            continue
        violations = result.validate_contract()
        if violations:
            problems.append(f"{dimension} violates the AuditResult contract: {violations}")

    return problems


async def run_sample(container: ServiceContainer, sample: Sample) -> Outcome:
    """Audit one sample through the real stack."""
    from app.decision_engine.report_builder import build_report

    started = time.perf_counter()
    audit_id = f"cal_{sample.sample_id}"
    try:
        context = await container.input_router.from_text(
            audit_id=audit_id,
            text=sample.content,
            prompt=sample.prompt,
            reference_source=sample.reference,
        )
        results = await container.orchestrator(audit_id).run(context)
        ordered = list(results.values())
        decision = container.decision_engine.decide(ordered)
        report = build_report(audit_id, decision, ordered)
    except Exception as exc:  # a corpus run must survive one bad sample
        return Outcome(
            sample=sample,
            report=None,
            elapsed=time.perf_counter() - started,
            error=f"{type(exc).__name__}: {exc}",
        )

    return Outcome(
        sample=sample,
        report=report,
        failures=_check(sample, report),
        elapsed=time.perf_counter() - started,
    )


async def run_corpus(
    samples: Sequence[Sample] | None = None,
    container: ServiceContainer | None = None,
) -> list[Outcome]:
    """Audit every sample, sequentially.

    Sequential on purpose. Each audit already fans out to eight engines and
    many LLM calls; running samples concurrently on top of that would collide
    with Groq's free-tier rate limit and measure the limiter rather than the
    auditor.
    """
    corpus = list(samples) if samples is not None else load_corpus()
    owned = container is None
    engine = container or build_container()
    try:
        outcomes = []
        for index, sample in enumerate(corpus, start=1):
            print(f"  [{index}/{len(corpus)}] {sample.label} …", flush=True)
            outcomes.append(await run_sample(engine, sample))
        return outcomes
    finally:
        if owned:
            await engine.aclose()


def _print_table(outcomes: list[Outcome]) -> None:
    """Print the Document 4 §11 results table."""
    print("\n" + "=" * 100)
    print("VALIDATION RESULTS (Document 4, §11)")
    print("=" * 100)
    print(
        f"{'SAMPLE':<32} {'EXPECTED':<26} {'OBSERVED':<22} {'TRUST':<10} "
        f"{'QUAL':<9} {'CONF':<6} {'':4}"
    )
    print("-" * 100)
    for outcome in outcomes:
        expected = outcome.sample.expect.get("overall") or outcome.sample.expect.get(
            "trust_not"
        )
        expected_text = (
            "/".join(str(e) for e in expected)[:25] if expected else "(invariants only)"
        )
        report = outcome.report
        trust = report.trust_verdict.verdict.value[:9] if report else "-"
        quality = (
            f"{report.quality_verdict.band.value[:4]}"
            f"{'' if report.quality_verdict.score is None else f' {report.quality_verdict.score:.2f}'}"
            if report
            else "-"
        )
        conf = f"{report.confidence.overall:.2f}" if report else "-"
        print(
            f"{outcome.sample.label:<32} {expected_text:<26} "
            f"{outcome.observed[:21]:<22} {trust:<10} {quality:<9} {conf:<6} "
            f"{'PASS' if outcome.passed else 'FAIL'}"
        )
        for failure in outcome.failures:
            print(f"{'':>32} └─ {failure}")

    passed = sum(1 for o in outcomes if o.passed)
    print("-" * 100)
    print(f"{passed}/{len(outcomes)} samples matched their expectations")

    # Separation is the claim; report it explicitly rather than leaving it to
    # be eyeballed from the table (Document 4, §11 success criteria).
    print("\nSEPARATION (the central claim):")
    for tier in ("good", "medium", "poor"):
        tiered = [o for o in outcomes if o.sample.tier == tier and o.report]
        if not tiered:
            continue
        verdicts: dict[str, int] = {}
        for outcome in tiered:
            verdicts[outcome.observed] = verdicts.get(outcome.observed, 0) + 1
        summary = ", ".join(f"{v}×{k}" for k, v in sorted(verdicts.items()))
        print(f"  {tier:<7} {summary}")


def _print_coverage(samples: list[Sample]) -> bool:
    """Report which required content categories the corpus covers."""
    found = coverage(samples)
    print("\nCORPUS COVERAGE (Work 6 required categories):")
    complete = True
    for kind in REQUIRED_KINDS:
        covering = [
            label for k, labels in found.items() if kind in k for label in labels
        ]
        mark = "ok  " if covering else "MISS"
        if not covering:
            complete = False
        print(f"  {mark} {kind:<28} {', '.join(sorted(set(covering))) or '—'}")
    return complete


async def _main(args: argparse.Namespace) -> int:
    samples = load_corpus()
    if not samples:
        print("No samples found under datasets/.", file=sys.stderr)
        return 2

    complete = _print_coverage(samples)

    container = build_container()
    if not container.settings.llm_configured:
        print(
            "\nGROQ_API_KEY is not configured, so every engine will degrade and "
            "every sample will report Unable to Verify.\n"
            "Set it in backend/.env (see .env.example) — calibration needs real "
            "measurements.",
            file=sys.stderr,
        )
        await container.aclose()
        return 3

    print(f"\nRunning {len(samples)} samples through the real stack "
          f"({container.settings.llm.model})…\n")
    started = time.perf_counter()
    try:
        outcomes = await run_corpus(samples, container)
    finally:
        await container.aclose()

    _print_table(outcomes)
    print(f"\nTotal wall-clock: {time.perf_counter() - started:.1f}s")

    if args.json:
        payload = [
            {
                "sample": o.sample.label,
                "kinds": list(o.sample.kinds),
                "expected": o.sample.expect,
                "observed": o.observed,
                "passed": o.passed,
                "failures": o.failures,
                "elapsed_s": round(o.elapsed, 2),
                "report": json.loads(o.report.model_dump_json()) if o.report else None,
            }
            for o in outcomes
        ]
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Full reports written to {args.json}")

    failed = [o for o in outcomes if not o.passed]
    return 1 if (failed or not complete) else 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run the validation corpus through the real auditor "
        "(Document 4, §11)."
    )
    parser.add_argument(
        "--json",
        type=__import__("pathlib").Path,
        default=None,
        help="Write the full reports to this file for inspection.",
    )
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
