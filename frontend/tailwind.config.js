/** @type {import('tailwindcss').Config} */

/**
 * Tailwind configuration.
 *
 * The palette encodes Document 4 §8's UX requirements rather than decorating
 * them. Trust and Quality get visually distinct scales because the two axes
 * must never read as one blended number, and the verdict colors are semantic —
 * `untrusted` is red, `unverified` is amber, and they are deliberately
 * different hues, because "we found a problem" and "we could not check" are
 * different statements and must never look alike.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Trust axis — non-compensatory. Cool, authoritative.
        trust: {
          50: '#eef4ff',
          100: '#dbe6fe',
          500: '#3b6bf5',
          600: '#2b52d4',
          700: '#2341a8',
          900: '#1a2f6b',
        },
        // Quality axis — compensatory. Deliberately a different family from
        // trust, so the two verdicts never read as one scale.
        quality: {
          50: '#f0fdf9',
          100: '#ccfbef',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
        },
        // Verdict semantics (Document 3, §11).
        verdict: {
          trusted: '#16a34a',
          caveats: '#65a30d',
          revision: '#ea580c',
          untrusted: '#dc2626',
          unverified: '#d97706',
        },
        // Severity (Document 2, §3).
        severity: {
          critical: '#b91c1c',
          high: '#dc2626',
          medium: '#ea580c',
          low: '#ca8a04',
          info: '#64748b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
