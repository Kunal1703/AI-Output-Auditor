/** Landing — an animated page that immediately explains the auditor. */

import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Cpu,
  FileSearch,
  GitCompare,
  Layers,
  ShieldCheck,
  Sparkles,
  Target,
} from 'lucide-react';
import { Button, Card, stagger } from '@/components/ui';
import { Gauge, LogoMark } from '@/components/brand';
import { VerdictBadge } from '@/components/report/verdict';

const FEATURES = [
  {
    icon: ShieldCheck,
    title: 'Grounding first',
    body: 'Faithfulness, hallucinations, and contradictions gate the verdict — no amount of polish buys back a fabricated fact.',
  },
  {
    icon: FileSearch,
    title: 'Evidence for everything',
    body: 'Every finding maps to a source span and an output span. Click a claim, see exactly where it came from.',
  },
  {
    icon: GitCompare,
    title: 'Human vs. LLM',
    body: 'Audit several outputs against one source and compare them side by side, with a clear ranked winner.',
  },
  {
    icon: Cpu,
    title: 'Local NLI, zero token cost',
    body: 'A local entailment model does the grounding work, so audits are cheap, fast, and reproducible.',
  },
];

const LAYERS = [
  { n: 1, icon: Target, name: 'Grounding', desc: 'Faithfulness · Numeric accuracy · Contradictions', tone: 'text-verdict-fail' },
  { n: 2, icon: Layers, name: 'Information Quality', desc: 'Coverage · Meaning preservation', tone: 'text-verdict-good' },
  { n: 3, icon: Sparkles, name: 'Presentation', desc: 'Readability · Conciseness · Objectivity', tone: 'text-verdict-excellent' },
];

export default function Landing() {
  return (
    <div className="space-y-24 pb-10">
      {/* Hero */}
      <section className="relative overflow-hidden pt-6">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-grid-fade [background-size:22px_22px] opacity-40" />
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <motion.div initial="hidden" animate="show" variants={stagger.container}>
            <motion.div variants={stagger.item}>
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-elevated px-3 py-1 text-xs font-medium text-content-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" /> Evidence-backed AI output auditing
              </span>
            </motion.div>
            <motion.h1
              variants={stagger.item}
              className="mt-5 text-balance text-4xl font-extrabold leading-[1.05] tracking-tight text-content sm:text-5xl lg:text-6xl"
            >
              Audit AI outputs against <span className="text-gradient">their source</span>.
            </motion.h1>
            <motion.p variants={stagger.item} className="mt-5 max-w-xl text-lg leading-relaxed text-content-muted">
              Veritas checks summaries and answers for faithfulness, accuracy, coverage, meaning, and
              bias — comparing human and LLM outputs side by side, with a traceable verdict for every claim.
            </motion.p>
            <motion.div variants={stagger.item} className="mt-8 flex flex-wrap gap-3">
              <Link to="/audit">
                <Button size="lg">
                  Start an audit <ArrowRight size={18} />
                </Button>
              </Link>
              <Link to="/audit?example=1">
                <Button size="lg" variant="secondary">
                  <Sparkles size={16} /> Try an example
                </Button>
              </Link>
            </motion.div>
            <motion.div variants={stagger.item} className="mt-6 flex items-center gap-5 text-xs text-content-subtle">
              <span>Source-only · no external knowledge</span>
              <span className="h-1 w-1 rounded-full bg-content-subtle" />
              <span>18 metrics · 3 layers</span>
            </motion.div>
          </motion.div>

          {/* Hero visual */}
          <motion.div
            initial={{ opacity: 0, scale: 0.94, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="relative"
          >
            <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-tr from-brand/20 via-transparent to-accent/20 blur-2xl" />
            <Card className="p-6">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-semibold text-content">
                  <LogoMark size={20} /> Comparative report
                </span>
                <span className="text-2xs text-content-subtle">2 outputs</span>
              </div>
              <div className="mt-5 flex items-center justify-around">
                <Gauge value={0.94} colorClass="text-verdict-excellent" label="Human" size={116} />
                <Gauge value={0.31} colorClass="text-verdict-fail" label="LLM" size={116} />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3">
                <div className="rounded-xl border border-border bg-elevated p-3">
                  <VerdictBadge verdict="Good" />
                  <p className="mt-2 text-2xs text-content-subtle">Faithful · complete</p>
                </div>
                <div className="rounded-xl border border-border bg-elevated p-3">
                  <VerdictBadge verdict="Fail" />
                  <p className="mt-2 text-2xs text-content-subtle">Wrong figure · contradiction</p>
                </div>
              </div>
            </Card>
            <motion.div
              animate={{ y: [0, -8, 0] }}
              transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
              className="absolute -bottom-5 -left-5 hidden rounded-xl border border-hairline bg-surface px-3 py-2 shadow-lift sm:block"
            >
              <p className="text-2xs font-medium text-content-muted">“$6.1B” contradicts source “$5.2B”</p>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Three layers */}
      <section>
        <div className="mb-8 text-center">
          <h2 className="text-2xl font-bold tracking-tight text-content">A non-compensatory framework</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-content-muted">
            Verdicts are layered. Grounding failures cap the result — presentation can only shape quality within that ceiling.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {LAYERS.map((l, i) => (
            <motion.div
              key={l.n}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, duration: 0.5 }}
            >
              <Card hover className="h-full p-6">
                <div className="flex items-center gap-3">
                  <span className={`grid h-10 w-10 place-items-center rounded-xl bg-elevated ${l.tone}`}>
                    <l.icon size={19} />
                  </span>
                  <div>
                    <p className="text-2xs font-medium uppercase tracking-wide text-content-subtle">Layer {l.n}</p>
                    <p className="text-sm font-semibold text-content">{l.name}</p>
                  </div>
                </div>
                <p className="mt-4 text-sm text-content-muted">{l.desc}</p>
              </Card>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.06, duration: 0.5 }}
            >
              <Card hover className="flex h-full items-start gap-4 p-6">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand/10 text-brand">
                  <f.icon size={20} />
                </span>
                <div>
                  <p className="text-base font-semibold text-content">{f.title}</p>
                  <p className="mt-1.5 text-sm leading-relaxed text-content-muted">{f.body}</p>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section>
        <Card className="relative overflow-hidden">
          <div className="absolute inset-0 -z-10 bg-gradient-to-tr from-brand/15 via-transparent to-accent/15" />
          <div className="flex flex-col items-center gap-5 px-6 py-14 text-center">
            <h2 className="text-2xl font-bold tracking-tight text-content sm:text-3xl">
              Paste a source. Add your outputs. See the truth.
            </h2>
            <p className="max-w-lg text-sm text-content-muted">
              Runs entirely against your source with a local NLI model — evidence you can inspect, not a black-box score.
            </p>
            <Link to="/audit">
              <Button size="lg">
                Start an audit <ArrowRight size={18} />
              </Button>
            </Link>
          </div>
        </Card>
      </section>
    </div>
  );
}
