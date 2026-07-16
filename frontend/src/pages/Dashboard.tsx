/**
 * Dashboard — the landing page.
 *
 * Document 4 §8, Landing Page: "explain the auditor; choose to start".
 *
 * The explanation is the page's actual job. A visitor who does not grasp that
 * trust and quality are separate axes will misread every report the system
 * produces — most of all the one where polished, well-written content comes back
 * *Untrusted* because of a single fabricated citation.
 */

import { Link } from 'react-router-dom';

const PRINCIPLES = [
  {
    title: 'Evidence-first',
    body: 'Every conclusion links to concrete evidence — a span, a passage, a source lookup. No verdict is asserted without something to point at.',
  },
  {
    title: 'Non-compensatory trust',
    body: 'One fabricated citation makes content untrustworthy no matter how well it scores elsewhere. Trust is a floor, not an average.',
  },
  {
    title: 'Honest uncertainty',
    body: 'When the evidence cannot settle the question, the auditor returns "Unable to Verify" rather than guessing. Undetermined is not the same as failed.',
  },
  {
    title: 'Explainable',
    body: 'Every score and finding is traceable and human-reviewable. The report says why, not just what.',
  },
];

const DIMENSIONS: { name: string; type: string; question: string }[] = [
  {
    name: 'Relevance',
    type: 'Hybrid',
    question: "Does it satisfy the user's instruction and intent?",
  },
  {
    name: 'Accuracy',
    type: 'Trust',
    question: 'Is every factual claim supported by the evidence?',
  },
  {
    name: 'Coverage',
    type: 'Hybrid',
    question: 'Does it include everything important from the source?',
  },
  {
    name: 'Credibility',
    type: 'Trust',
    question: 'Are the sources trustworthy, cited correctly, and real?',
  },
  {
    name: 'Novelty',
    type: 'Quality',
    question: 'Does it communicate efficiently, without padding?',
  },
  {
    name: 'Readability',
    type: 'Quality',
    question: 'Is it clear, coherent, and well structured?',
  },
  {
    name: 'Engagement',
    type: 'Quality',
    question: 'Does it help the reader without manipulating them?',
  },
  {
    name: 'Diversity',
    type: 'Quality',
    question: 'Where it matters, are legitimate perspectives represented?',
  },
];

const TYPE_STYLES: Record<string, string> = {
  Trust: 'bg-trust-900/40 text-trust-100 border-trust-700/50',
  Quality: 'bg-quality-700/20 text-quality-100 border-quality-700/50',
  Hybrid: 'bg-slate-700/40 text-slate-200 border-slate-600/50',
};

/** The landing page. */
export default function Dashboard() {
  return (
    <div className="space-y-10">
      <section className="pt-4">
        <h1 className="max-w-3xl text-3xl font-bold leading-tight text-slate-100 sm:text-4xl">
          Know which AI output you can trust — and why.
        </h1>
        <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-400">
          Confident, fluent, well-formatted text can still be hallucinated,
          mis-sourced, off-instruction, or incomplete. This auditor evaluates
          AI-generated content across eight dimensions and returns an
          evidence-backed verdict — not a number.
        </p>
        <div className="mt-6 flex items-center gap-3">
          <Link
            to="/audit"
            className="rounded bg-trust-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-trust-500"
          >
            Start an audit
          </Link>
          <Link
            to="/results"
            className="rounded border border-slate-700 px-5 py-2.5 text-sm text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
          >
            View a report
          </Link>
        </div>
      </section>

      {/* The two-axis idea, stated up front — it is the thing most readers get
          wrong, and it changes how every report should be read. */}
      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-trust-700/40 bg-trust-900/10 p-5">
          <h2 className="text-sm font-semibold text-trust-100">
            Trust · non-compensatory
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            Is there anything here that makes it unsafe to rely on? A single
            critical finding — a contradicted claim, a fabricated citation —
            gates the verdict to <strong>Untrusted</strong> regardless of every
            other score. Strengths never average a critical failure away.
          </p>
        </div>
        <div className="rounded-lg border border-quality-700/40 bg-quality-700/5 p-5">
          <h2 className="text-sm font-semibold text-quality-100">
            Quality · compensatory
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            How well-made is it? Here strengths genuinely can offset weaknesses.
            Quality is reported <strong>separately</strong> and never gates
            trust — content can be polished yet untrustworthy, or accurate yet
            badly organized.
          </p>
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Eight audit engines
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {DIMENSIONS.map((d) => (
            <div
              key={d.name}
              className="rounded-lg border border-slate-800 bg-slate-900 p-4"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-200">
                  {d.name}
                </span>
                <span
                  className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${TYPE_STYLES[d.type]}`}
                >
                  {d.type}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                {d.question}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">
          How it reasons
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {PRINCIPLES.map((p) => (
            <div
              key={p.title}
              className="rounded-lg border border-slate-800 bg-slate-900 p-4"
            >
              <h3 className="text-sm font-medium text-slate-200">{p.title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
