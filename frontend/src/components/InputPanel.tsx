/**
 * InputPanel — collects the content to audit.
 *
 * Document 4 §8, Input Selection: "tabs: Text | URL | File; optional prompt &
 * reference source".
 *
 * The two optional fields are worth understanding rather than treating as
 * extras, which is why the panel explains them inline:
 *
 * - **prompt** — the original instruction. Relevance, Engagement, and Diversity
 *   measure the output *against stated intent*. Without it, those three have
 *   nothing to measure against.
 * - **reference_source** — ground truth. Optional for Accuracy, but **Coverage
 *   requires it in order to score** (Document 2, §6.1): completeness is
 *   meaningless without something to be complete with respect to.
 *
 * @remarks
 * The layout and submit contract are real; the file tab and its submission
 * wiring land in Milestone 6 with the content extractor.
 */

import { useState } from 'react';
import type { AuditRequest } from '@/api/types';

type Tab = 'text' | 'url' | 'file';

interface InputPanelProps {
  /** Invoked with the assembled request when the user submits text or a URL. */
  onSubmit?: (request: AuditRequest) => void;
  /**
   * Invoked when the user submits a file. Separate from {@link onSubmit}
   * because the file endpoint is multipart, not JSON — a `File` cannot travel
   * inside an `AuditRequest`.
   */
  onSubmitFile?: (file: File, prompt?: string, referenceSource?: string) => void;
  /** Disables the form while an audit is running. */
  busy?: boolean;
}

/** What the backend's content extractor can actually read. */
const ACCEPTED_FILES = '.txt,.md,.markdown,.rst,.text,.pdf,.html,.htm';

const TABS: { id: Tab; label: string }[] = [
  { id: 'text', label: 'Text' },
  { id: 'url', label: 'URL' },
  { id: 'file', label: 'File' },
];

/** Input collection panel with Text / URL / File tabs. */
export default function InputPanel({
  onSubmit,
  onSubmitFile,
  busy = false,
}: InputPanelProps) {
  const [tab, setTab] = useState<Tab>('text');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [prompt, setPrompt] = useState('');
  const [referenceSource, setReferenceSource] = useState('');

  const canSubmit =
    !busy &&
    (tab === 'text'
      ? text.trim().length > 0
      : tab === 'url'
        ? url.trim().length > 0
        : file !== null);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;

    if (tab === 'file' && file) {
      onSubmitFile?.(file, prompt.trim() || undefined, referenceSource.trim() || undefined);
      return;
    }

    onSubmit?.({
      ...(tab === 'text' ? { text: text.trim() } : { url: url.trim() }),
      prompt: prompt.trim() || null,
      reference_source: referenceSource.trim() || null,
      options: { external_retrieval: false },
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-slate-800 bg-slate-900 p-6"
    >
      <div className="mb-5 flex gap-1 border-b border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
              tab === t.id
                ? 'border-trust-500 text-slate-100'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'text' && (
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-300">
            AI-generated output
          </span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder="Paste the AI-generated content you want audited…"
            className="w-full resize-y rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-trust-500 focus:outline-none"
          />
        </label>
      )}

      {tab === 'url' && (
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-300">
            Article URL
          </span>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/article"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-trust-500 focus:outline-none"
          />
          <span className="mt-1.5 block text-xs text-slate-500">
            The page is fetched and cleaned into article text before auditing.
          </span>
        </label>
      )}

      {tab === 'file' && (
        <label className="block cursor-pointer">
          <span className="mb-1.5 block text-sm font-medium text-slate-300">
            Document
          </span>
          <div className="grid place-items-center rounded border border-dashed border-slate-700 py-10 text-center transition hover:border-slate-600">
            <input
              type="file"
              accept={ACCEPTED_FILES}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
            {file ? (
              <>
                <p className="text-sm font-medium text-slate-200">{file.name}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {(file.size / 1024).toFixed(0)} KB · click to choose another
                </p>
              </>
            ) : (
              <>
                <p className="text-sm text-slate-400">
                  Choose a document to audit
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  txt, md, pdf, or html · up to 10MB
                </p>
              </>
            )}
          </div>
          <span className="mt-1.5 block text-xs text-slate-500">
            A scanned PDF with no text layer cannot be audited — it needs OCR
            first.
          </span>
        </label>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-300">
            Original prompt <span className="text-slate-600">(optional)</span>
          </span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="The instruction the AI was given…"
            className="w-full resize-y rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-trust-500 focus:outline-none"
          />
          <span className="mt-1.5 block text-xs text-slate-500">
            Relevance, Engagement, and Diversity measure the output against
            stated intent. Without it, they have nothing to compare to.
          </span>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-300">
            Reference source <span className="text-slate-600">(optional)</span>
          </span>
          <textarea
            value={referenceSource}
            onChange={(e) => setReferenceSource(e.target.value)}
            rows={3}
            placeholder="Ground-truth text to verify against…"
            className="w-full resize-y rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-trust-500 focus:outline-none"
          />
          <span className="mt-1.5 block text-xs text-slate-500">
            Accuracy checks against this first. Coverage needs it to score at
            all.
          </span>
        </label>
      </div>

      <div className="mt-6 flex items-center justify-end">
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded bg-trust-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-600"
        >
          {busy ? 'Auditing…' : 'Run audit'}
        </button>
      </div>
    </form>
  );
}
